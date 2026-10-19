"""The wrap and session styles: ``instrument()`` and ``session()`` (DESIGNS No. 15)."""

import contextlib

import anyio

from harnessweaver.core.context import RunContext
from harnessweaver.core.errors import (
    HarnessError,
    RunBlocked,
    RunInterrupted,
    UnknownProvider,
    classify,
)
from harnessweaver.core.hooks import HookPoint, RunStartEvent
from harnessweaver.core.plugins import AdapterInfo
from harnessweaver.core.results import RunResult
from harnessweaver.core.runs import RunStatus
from harnessweaver.core.telemetry import Telemetry
from harnessweaver.harness.approvals import ApprovalMixin
from harnessweaver.harness.records import (
    LiveRun,
    PendingSession,
)

__all__ = ["WrapMixin"]


class WrapMixin(ApprovalMixin):
    """Governing code the app runs itself."""

    def _adapter_for(self, target: object, name: str | None) -> AdapterInfo:
        if name is not None:
            return self._registry.adapter(name)
        kind = type(target)
        for cls in kind.__mro__:
            root = cls.__module__.split(".", 1)[0]
            if root == "builtins":
                continue
            try:
                self._registry.ensure(root)
            except UnknownProvider:
                continue
            names = {f"{root}.{cls.__name__}", f"{cls.__module__}.{cls.__qualname__}"}
            for info in self._registry.adapters():
                if names & set(info.wraps):
                    return info
        raise UnknownProvider(
            f"no installed plugin has an adapter for {kind.__module__}.{kind.__qualname__}",
            type=f"{kind.__module__}.{kind.__qualname__}",
        )

    async def _open_session(self, pending: "PendingSession") -> RunContext:
        task = self._tasks.get(pending.task) if pending.task is not None else None
        run = await self._new_run(
            task,
            pending.task,
            None,
            principal=pending.principal,
            tenant=pending.tenant,
            budget=pending.budget,
            idempotency_key=None,
            attributes=pending.attributes,
            can_suspend=False,
        )
        assert isinstance(run, LiveRun)
        pending.run = run
        stack = contextlib.ExitStack()
        span = stack.enter_context(self._telemetry.run_scope(run.ctx.envelope))
        run.ctx.set_trace_id(Telemetry.trace_id(span))
        stack.enter_context(run.ctx.activate())
        pending.stack, pending.span = stack, span
        start = await run.ctx.emit(HookPoint.RUN_START, RunStartEvent(task=pending.task))
        try:
            run.ctx.halt_on(start)
            await run.ctx.authorize_run()
        except RunInterrupted as exc:
            await self._close_session(pending, exc)
            raise
        await self._set_status(run, RunStatus.RUNNING)
        return run.ctx

    async def _close_session(
        self, pending: "PendingSession", exc: BaseException | None
    ) -> RunResult:
        run = pending.run
        assert run is not None
        if pending.result is not None:
            return pending.result
        result: RunResult | None = None
        try:
            with anyio.CancelScope(shield=True):
                if exc is None:
                    result = await self._finish(run, RunStatus.COMPLETED, output=run.ctx.output)
                elif isinstance(exc, RunBlocked):
                    result = await self._finish(run, RunStatus.BLOCKED, error=exc)
                elif isinstance(exc, RunInterrupted):
                    result = await self._finish(run, RunStatus.ESCALATED, error=exc)
                elif isinstance(exc, Exception):
                    error = exc if isinstance(exc, HarnessError) else classify(exc)
                    result = await self._fail(run, error)
                else:
                    result = await self._finish(run, RunStatus.CANCELLED)
        finally:
            if result is not None and pending.span is not None:
                Telemetry.run_done(pending.span, result)
            if pending.stack is not None:
                pending.stack.close()
                pending.stack = None
        assert result is not None
        pending.result = result
        return result
