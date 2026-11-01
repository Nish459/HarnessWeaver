"""Pausing a run for approval, answering it, resuming and cancelling (DESIGNS No. 18)."""

from datetime import timedelta

from loguru import logger
from pydantic import JsonValue, ValidationError

from harnessweaver.core.budgets import BudgetMeter
from harnessweaver.core.envelope import Principal
from harnessweaver.core.errors import (
    NotFound,
    PolicyDenied,
    RunBlocked,
    RunEscalated,
    ValidationFailed,
    from_known,
)
from harnessweaver.core.hooks import HookPoint
from harnessweaver.core.ids import new_id
from harnessweaver.core.results import RunResult
from harnessweaver.core.runs import ApprovalDecision, ApprovalRequest, RunStatus
from harnessweaver.core.state import Checkpoint, Grant, RunRecord
from harnessweaver.harness.records import ApprovalAnswer, Channel, LiveRun, TaskEntry
from harnessweaver.harness.runs import RunMixin
from harnessweaver.spec.models import TaskApprovals

__all__ = ["ApprovalMixin"]


class ApprovalMixin(RunMixin):
    """Approvals, resumption and cancellation."""

    def _task_approvals(self, task: TaskEntry | None) -> TaskApprovals:
        if task is not None and task.spec.approvals is not None:
            return task.spec.approvals
        return TaskApprovals()

    def _approver_role(self, task: TaskEntry | None, role: str | None) -> str | None:
        """Who must approve: the role the step that asked named, else the task's
        ``approvals.approver_role``, else the spec's. ``authorize`` resolves it the
        same way, so a dry run names the role a real run waits for."""
        return (
            role
            or self._task_approvals(task).approver_role
            or self._effective.spec.approvals.approver_role
        )

    def _approval_timeout(self, run: LiveRun) -> timedelta | None:
        timeout = self._task_approvals(run.task).timeout
        return timeout if timeout is not None else self._effective.spec.approvals.timeout

    async def _suspend(self, run: LiveRun) -> RunResult:
        ctx = run.ctx
        pending = ctx.pending
        if pending is None:  # pragma: no cover - RunSuspended always records what it waits on
            return await self._finish(run, RunStatus.ESCALATED)
        now = self._clock.now()
        timeout = self._approval_timeout(run)
        approval = ApprovalRequest(
            approval_id=new_id("apr"),
            run_id=ctx.run_id,
            reason=pending.reason,
            approver_role=self._approver_role(run.task, pending.approver_role),
            call=pending.call,
            tool=pending.tool,
            requested_at=now,
            expires_at=now + timeout if timeout is not None else None,
        )
        # A runner that re-runs its work repeats calls it already ran: they need their grants.
        rerun = run.task is not None and not run.task.resumable
        checkpoint = Checkpoint(
            run_id=ctx.run_id,
            task=run.record.task,
            input=run.input,
            resume=ctx.resume_point,
            meter=ctx.meter.snapshot(),
            labels=ctx.envelope.labels,
            grants=(*(ctx.spent_grants if rerun else ()), *ctx.grants),
            approval=approval,
            approval_args=pending.edited_args,
            approval_hook=pending.hook.value,  # pyright: ignore[reportArgumentType]
            approval_digest=pending.digest,
            time_left=ctx.time_left(),
            context_ids=tuple(sorted(ctx.context_ids)),
        )
        await self._state.put_checkpoint(checkpoint)
        self._telemetry.approval(ctx.run_id, approval.approval_id, "requested")
        ctx.trace.note(
            "harness.approvals",
            pending.reason,
            hook=pending.hook,
            details={"approval_id": approval.approval_id},
        )
        result = self._result(run, RunStatus.AWAITING_APPROVAL, approval=approval)
        await self._store(run, RunStatus.AWAITING_APPROVAL, result)
        await self._event(run, "approval", approval=approval)
        result = await self._notify(run, approval, result)
        self._close(run.channel)
        return result

    async def _notify(
        self, run: LiveRun, approval: ApprovalRequest, result: RunResult
    ) -> RunResult:
        """Tell approvers through ``approvals.use``. The request is already saved, so a
        failing channel is traced (R13) and the run keeps waiting."""
        channel = self._approval_channel
        if channel is None:
            return result
        try:
            await channel.notify(approval, run.ctx.envelope)
        except Exception as exc:
            reason = f"the approval channel failed ({type(exc).__name__}); the request is saved"
            run.ctx.trace.note(
                "harness.approvals",
                reason,
                code="approval_notify_failed",
                details={"approval_id": approval.approval_id},
            )
            logger.warning("run {} approval {}: {}", run.ctx.run_id, approval.approval_id, reason)
            result = self._result(run, RunStatus.AWAITING_APPROVAL, approval=approval)
            run.record = run.record.model_copy(update={"result": result})
            await self._state.put_run(run.record)
        return result

    async def _restore(self, record: RunRecord, checkpoint: Checkpoint) -> LiveRun:
        task = self._task(record.task) if record.task is not None else None
        envelope = record.envelope.with_clock(self._clock)
        deadline = (
            self._clock.now() + checkpoint.time_left if checkpoint.time_left is not None else None
        )
        envelope = envelope.model_copy(update={"labels": checkpoint.labels, "deadline": deadline})
        channel = self._channels.setdefault(record.run_id, Channel())
        channel.closed = False
        channel.seq = max([e.seq for e in await self._state.events(record.run_id)], default=-1) + 1
        previous = record.result.trace if record.result is not None else ()
        recorded = 0
        if self._effective.spec.state.record:
            recorded = len(await self._state.recording(record.run_id))
        ctx = self._context(
            envelope,
            task.info if task is not None else None,
            channel,
            meter=BudgetMeter.restore(record.envelope.budget, checkpoint.meter),
            trace_events=previous,
            grants=checkpoint.grants,
            context_ids=checkpoint.context_ids,
            recorded=recorded,
        )
        return LiveRun(record, ctx, task, checkpoint.input, channel)

    async def approve(
        self,
        run_id: str,
        approval_id: str,
        decision: ApprovalAnswer = "approve",
        *,
        approver: Principal | str,
        edited_args: dict[str, JsonValue] | None = None,
        reason: str | None = None,
    ) -> RunResult:
        """Answer a pending approval and continue the run (DESIGNS No. 18).

        1. Checks the approver holds the request's ``approver_role``.
        2. Claims the request in the state store, so one answer wins (ADR-0044).
        3. Fires ``approval.resolved``.
        4. On ``approve`` or ``edit``, resumes; edited arguments go through
           ``tool.before`` again. On ``reject``, the run ends ``blocked``.

        An expired request ends the run as ``approvals.on_timeout`` says.

        Raises:
            NotFound: If the run has no such pending approval, another answer won it,
                or this process is still suspending the run.
            PolicyDenied: If the approver lacks the required role.
            ValidationFailed: For an ``edit`` without arguments, or of an output.
        """
        record = await self._state.get_run(run_id)
        checkpoint = await self._state.get_checkpoint(run_id)
        if (
            record is None
            or record.status is not RunStatus.AWAITING_APPROVAL
            or checkpoint is None
            or checkpoint.approval is None
            or checkpoint.approval.approval_id != approval_id
            or run_id in self._active
        ):
            raise NotFound(f"run {run_id} has no pending approval {approval_id!r}", run_id=run_id)
        request = checkpoint.approval
        who = approver if isinstance(approver, Principal) else Principal(id=approver)
        if request.approver_role is not None and not who.has_role(request.approver_role):
            raise PolicyDenied(
                f"approving needs the role {request.approver_role!r}", approval_id=approval_id
            )
        try:
            answer = ApprovalDecision(
                approval_id=approval_id,
                decision=decision,
                approver=who,
                edited_args=edited_args,
                reason=reason,
            )
        except ValidationError as exc:
            raise from_known(exc) or ValidationFailed("invalid approval") from None
        if answer.decision == "edit" and checkpoint.approval_hook != HookPoint.TOOL_BEFORE.value:
            raise ValidationFailed("only a tool call's arguments can be edited")
        expired = request.expires_at is not None and self._clock.now() > request.expires_at
        grants = checkpoint.grants
        if (
            not expired
            and answer.decision != "reject"
            and checkpoint.approval_hook
            and checkpoint.approval_digest
        ):
            carried = checkpoint.approval_args
            grant = Grant(
                hook=checkpoint.approval_hook,
                digest=checkpoint.approval_digest,
                # Approving a request that shows edited arguments approves those arguments.
                decision=answer.model_copy(update={"decision": "edit", "edited_args": carried})
                if answer.decision == "approve" and carried is not None
                else answer,
            )
            grants = (*grants, grant)
        # Claim first, so a losing answer leaves nothing behind. The claim also persists the
        # answer before resuming, so a crash doesn't lose it (resume() continues).
        resolved = checkpoint.model_copy(
            update={"approval": None, "approval_args": None, "grants": grants}
        )
        if not await self._state.claim_approval(resolved, approval_id):
            raise NotFound(f"run {run_id} has no pending approval {approval_id!r}", run_id=run_id)
        run = await self._restore(record, resolved)
        self._telemetry.approval(run_id, approval_id, answer.decision)
        if expired:
            return await self._expire(run)
        if checkpoint.approval_hook and checkpoint.approval_digest:
            await run.ctx.record(
                "approval",
                checkpoint.approval_digest,
                hook=checkpoint.approval_hook,
                decision=answer,
            )
        return await self._drive(run, resolved, (request, answer))

    async def _expire(self, run: LiveRun) -> RunResult:
        on_timeout = (
            self._task_approvals(run.task).on_timeout or self._effective.spec.approvals.on_timeout
        )
        reason = "the approval request expired"
        run.ctx.trace.note("harness.approvals", reason, code="approval_timeout")
        if on_timeout == "reject":
            return await self._finish(
                run, RunStatus.BLOCKED, error=RunBlocked(reason, code="approval_timeout")
            )
        return await self._finish(
            run, RunStatus.ESCALATED, error=RunEscalated(reason, code="approval_timeout")
        )

    async def resume(self, run_id: str) -> RunResult:
        """Continue a run whose approval was answered but which didn't finish (a crash).

        Raises:
            NotFound: If the run has nothing to resume, or is still waiting for approval.
        """
        record = await self._state.get_run(run_id)
        checkpoint = await self._state.get_checkpoint(run_id)
        if record is None or checkpoint is None or record.status.is_terminal:
            raise NotFound(f"run {run_id} has nothing to resume", run_id=run_id)
        if checkpoint.approval is not None:
            raise NotFound(f"run {run_id} is still waiting for approval", run_id=run_id)
        if run_id in self._active:
            raise NotFound(f"run {run_id} is already running here", run_id=run_id)
        return await self._drive(await self._restore(record, checkpoint), checkpoint)

    async def cancel(self, run_id: str) -> RunResult:
        """Cancel a run that is running here or waiting for approval.

        A finished run is returned unchanged.

        Raises:
            NotFound: For an unknown run.
        """
        active = self._active.get(run_id)
        if active is not None:
            active.scope.cancel()
            await active.done.wait()
            return await self.result(run_id)
        record = await self._state.get_run(run_id)
        if record is None:
            raise NotFound(f"no run {run_id}", run_id=run_id)
        if record.status.is_terminal and record.result is not None:
            return record.result
        checkpoint = await self._state.get_checkpoint(run_id) or Checkpoint(run_id=run_id)
        if checkpoint.approval is not None:
            # An answer racing this cancel must not also resume the run (ADR-0044).
            resolved = checkpoint.model_copy(update={"approval": None})
            if not await self._state.claim_approval(resolved, checkpoint.approval.approval_id):
                return await self.result(run_id)
        run = await self._restore(record, checkpoint)
        return await self._finish(run, RunStatus.CANCELLED)
