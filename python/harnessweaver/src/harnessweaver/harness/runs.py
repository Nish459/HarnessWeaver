"""Running tasks: ``run``, ``submit``, ``result``, and how a run starts and ends."""

from abc import ABC, abstractmethod
from collections.abc import Mapping
from typing import Any

import anyio
from loguru import logger
from pydantic import BaseModel, JsonValue, ValidationError

from harnessweaver.core.budgets import BudgetMeter
from harnessweaver.core.context import RunContext, TaskInfo
from harnessweaver.core.envelope import Budget, Envelope, Principal
from harnessweaver.core.errors import (
    DeadlineExceeded,
    HarnessError,
    NotFound,
    RunBlocked,
    RunInterrupted,
    RunSuspended,
    SpecError,
    ValidationFailed,
    classify,
    from_known,
)
from harnessweaver.core.hooks import HookPoint, RunStartEvent
from harnessweaver.core.ids import new_id
from harnessweaver.core.results import RunResult
from harnessweaver.core.runs import ApprovalDecision, ApprovalRequest, RunStatus
from harnessweaver.core.state import Checkpoint, RunRecord
from harnessweaver.core.telemetry import Telemetry
from harnessweaver.harness.endings import EndingMixin
from harnessweaver.harness.records import (
    ActiveRun,
    Channel,
    LiveRun,
    TaskEntry,
)
from harnessweaver.runners._output import check_output, give_up, to_json

__all__ = ["RunMixin"]


class RunMixin(EndingMixin, ABC):
    """How runs start, execute, fail and finish (DESIGNS No. 7, No. 18)."""

    @abstractmethod
    async def _suspend(self, run: LiveRun) -> RunResult:
        """Pause ``run`` for approval (implemented by :class:`ApprovalMixin`)."""

    async def _new_run(
        self,
        task: TaskEntry | None,
        task_name: str | None,
        input: Any,
        *,
        principal: Principal | str,
        tenant: str,
        budget: Budget,
        idempotency_key: str | None,
        attributes: Mapping[str, str] | None,
        can_suspend: bool = True,
    ) -> LiveRun | RunResult:
        run_id = new_id("run")
        if idempotency_key is not None and task_name is not None:
            owner = await self._state.claim_idempotency(tenant, task_name, idempotency_key, run_id)
            if owner != run_id:
                return await self.result(owner)
        envelope = Envelope.new(
            tenant=tenant,
            principal=principal,
            task=task_name,
            task_version=task.spec.version if task is not None else None,
            budget=budget,
            clock=self._clock,
            run_id=run_id,
            idempotency_key=idempotency_key,
            attributes=dict(attributes or {}),
        )
        now = self._clock.now()
        data = to_json(input)
        record = RunRecord(
            run_id=run_id,
            tenant=tenant,
            task=task_name,
            status=RunStatus.PENDING,
            envelope=envelope,
            input=data,
            created_at=now,
            updated_at=now,
        )
        await self._state.put_run(record)
        channel = self._channels.setdefault(run_id, Channel())
        info = task.info if task is not None else self._session_info(task_name)
        ctx = self._context(
            envelope, info, channel, meter=BudgetMeter(budget), can_suspend=can_suspend
        )
        await self._set_status(run := LiveRun(record, ctx, task, data, channel), RunStatus.PENDING)
        return run

    def _session_info(self, name: str | None) -> TaskInfo | None:
        if name is None:
            return None
        validation = self._effective.spec.validation
        return TaskInfo(
            name=name, max_repairs=validation.max_repairs, on_failure=validation.on_failure
        )

    async def run(
        self,
        task: str,
        input: Any = None,
        *,
        principal: Principal | str = "anonymous",
        tenant: str = "default",
        idempotency_key: str | None = None,
        budget: Mapping[str, object] | None = None,
        attributes: Mapping[str, str] | None = None,
    ) -> RunResult:
        """Run ``task`` to a terminal state, or until it suspends for approval.

        A repeated ``idempotency_key`` returns the first run's result instead
        of running again (DESIGNS No. 18). ``budget`` may lower the task's
        ``overridable`` limits for this run (R10).

        Raises:
            NotFound: For an unknown task.
            BoundViolation: For a budget override that isn't allowed.
        """
        prepared = await self._prepare(
            task, input, principal, tenant, idempotency_key, budget, attributes
        )
        if isinstance(prepared, RunResult):
            return prepared
        return await self._drive(prepared)

    async def submit(
        self,
        task: str,
        input: Any = None,
        *,
        principal: Principal | str = "anonymous",
        tenant: str = "default",
        idempotency_key: str | None = None,
        budget: Mapping[str, object] | None = None,
        attributes: Mapping[str, str] | None = None,
    ) -> str:
        """Start ``task`` in the background and return its run id at once.

        Needs ``async with harness:``. Follow it with :meth:`stream` and
        :meth:`result`.

        Raises:
            SpecError: Outside ``async with harness:``.
        """
        if self._group is None:
            raise SpecError("submit() needs an open harness: use 'async with harness:'")
        prepared = await self._prepare(
            task, input, principal, tenant, idempotency_key, budget, attributes
        )
        if isinstance(prepared, RunResult):
            return prepared.run_id
        self._active[prepared.ctx.run_id] = ActiveRun(anyio.CancelScope(), anyio.Event())
        self._group.start_soon(self._drive, prepared)
        return prepared.ctx.run_id

    async def _prepare(
        self,
        task: str,
        input: Any,
        principal: Principal | str,
        tenant: str,
        idempotency_key: str | None,
        budget: Mapping[str, object] | None,
        attributes: Mapping[str, str] | None,
    ) -> LiveRun | RunResult:
        found = self._task(task)
        limits = self._effective.run_budget(task, budget)
        return await self._new_run(
            found,
            task,
            input,
            principal=principal,
            tenant=tenant,
            budget=limits,
            idempotency_key=idempotency_key,
            attributes=attributes,
        )

    async def _drive(
        self,
        run: LiveRun,
        checkpoint: Checkpoint | None = None,
        answered: tuple[ApprovalRequest, ApprovalDecision] | None = None,
    ) -> RunResult:
        run_id = run.ctx.run_id
        active = self._active.setdefault(run_id, ActiveRun(anyio.CancelScope(), anyio.Event()))
        try:
            result: RunResult | None = None
            try:
                with active.scope:
                    result = await self._execute(run, checkpoint, answered)
            except anyio.get_cancelled_exc_class():
                # The caller was cancelled: record the run as cancelled, then let it go.
                with anyio.CancelScope(shield=True):
                    await self._finish(run, RunStatus.CANCELLED)
                raise
            if result is None:
                result = await self._finish(run, RunStatus.CANCELLED)
            return result
        finally:
            active.done.set()
            self._active.pop(run_id, None)

    async def _execute(
        self,
        run: LiveRun,
        checkpoint: Checkpoint | None,
        answered: tuple[ApprovalRequest, ApprovalDecision] | None,
    ) -> RunResult:
        with self._telemetry.run_scope(run.ctx.envelope) as span:
            run.ctx.set_trace_id(Telemetry.trace_id(span))
            result = await self._execute_steps(run, checkpoint, answered)
            Telemetry.run_done(span, result)
            return result

    async def _execute_steps(
        self,
        run: LiveRun,
        checkpoint: Checkpoint | None,
        answered: tuple[ApprovalRequest, ApprovalDecision] | None,
    ) -> RunResult:
        ctx = run.ctx
        with ctx.activate():
            try:
                left = ctx.time_left()
                with anyio.fail_after(left.total_seconds() if left is not None else None):
                    output = await self._steps(run, checkpoint, answered)
            except RunSuspended:
                return await self._suspend(run)
            except RunInterrupted as exc:
                status = RunStatus.BLOCKED if isinstance(exc, RunBlocked) else RunStatus.ESCALATED
                return await self._finish(run, status, error=exc)
            except HarnessError as exc:
                return await self._fail(run, exc)
            except TimeoutError:
                return await self._fail(run, DeadlineExceeded("the run passed its deadline"))
            except Exception as exc:
                logger.warning("run {} failed with {}", ctx.run_id, type(exc).__name__)
                return await self._fail(run, from_known(exc) or classify(exc))
            return await self._finish(run, RunStatus.COMPLETED, output=output)

    async def _steps(
        self,
        run: LiveRun,
        checkpoint: Checkpoint | None,
        answered: tuple[ApprovalRequest, ApprovalDecision] | None,
    ) -> JsonValue:
        ctx, task = run.ctx, run.task
        assert task is not None
        if checkpoint is None:
            start = await ctx.emit(
                HookPoint.RUN_START, RunStartEvent(task=task.name, input=run.input)
            )
            ctx.halt_on(start)
            await ctx.authorize_run()
            await self._set_status(run, RunStatus.RUNNING)
            run.input = await ctx.check_input(run.input)
            ctx.input = run.input
        else:
            ctx.input = run.input
            await self._set_status(run, RunStatus.RUNNING)
            if answered is not None:
                request, decision = answered
                await ctx.approval_resolved(request, decision)
                if decision.decision == "reject":
                    raise RunBlocked(
                        "the approver rejected the step",
                        hook=HookPoint.APPROVAL_RESOLVED.value,
                        code="approval_rejected",
                    )
        value = self._typed_input(task, run.input)
        output = await task.runner.execute(ctx, value, checkpoint.resume if checkpoint else None)
        return await self._checked_output(ctx, output)

    @staticmethod
    async def _checked_output(ctx: RunContext, output: Any) -> JsonValue:
        """The final output, past ``output.before`` whichever runner made it (R1, R4).

        A runner may have checked this very value already (direct, ``s.generate``,
        ``s.validate``), so only a value the run hasn't accepted fires the hook. There is
        nobody left to repair it here, so a ``Retry`` ends the run as ``on_failure`` says.
        A ``Suspend`` re-runs the runner after the approval, and an identical output then
        matches the grant.
        """
        final = to_json(output)
        if ctx.output_accepted(final):
            return final
        output_type = ctx.task.output_type if ctx.task is not None else None
        checked, problem = await check_output(ctx, output, output_type, 0)
        if problem is not None:
            give_up(ctx, problem, 0)
        return to_json(checked)

    @staticmethod
    def _typed_input(task: TaskEntry, value: JsonValue) -> Any:
        model = task.info.input_type
        if model is None or model is str:
            return value
        try:
            if issubclass(model, BaseModel):
                return model.model_validate(value)
            return value
        except ValidationError as exc:
            raise from_known(exc) or ValidationFailed("invalid input") from None

    async def result(self, run_id: str) -> RunResult:
        """The latest state of a run.

        Raises:
            NotFound: For an unknown run.
        """
        record = await self._state.get_run(run_id)
        if record is None:
            raise NotFound(f"no run {run_id}", run_id=run_id)
        if record.result is not None:
            return record.result
        return RunResult(
            run_id=run_id,
            task=record.task,
            task_version=record.envelope.task_version,
            status=record.status,
            started_at=record.created_at,
        )
