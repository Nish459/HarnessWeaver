"""How a run ends: failing, finishing, and recording its result and status."""

from typing import Any

from pydantic import JsonValue

from harnessweaver.core.errors import (
    HarnessError,
    RunBlocked,
)
from harnessweaver.core.hooks import HookPoint, RunEndEvent, RunErrorEvent
from harnessweaver.core.outcomes import Retry
from harnessweaver.core.results import RunResult
from harnessweaver.core.runs import RunStatus
from harnessweaver.harness.base import HarnessBase
from harnessweaver.harness.records import LiveRun

__all__ = ["EndingMixin"]


class EndingMixin(HarnessBase):
    """Ending runs: ``run.error`` and ``run.end``, the result, and the stored status."""

    async def _fail(self, run: LiveRun, error: HarnessError) -> RunResult:
        ctx = run.ctx
        info = error.to_info()
        result = await ctx.emit(
            HookPoint.RUN_ERROR, RunErrorEvent(error=info), check_deadline=False
        )
        if isinstance(result.outcome, Retry):
            ctx.trace.note(
                "harness",
                "Retry at run.error isn't supported; the run fails",
                hook=HookPoint.RUN_ERROR,
            )
        return await self._finish(run, RunStatus.FAILED, error_info=result.event.error)

    async def _finish(
        self,
        run: LiveRun,
        status: RunStatus,
        *,
        output: JsonValue = None,
        error: HarnessError | None = None,
        error_info: Any = None,
    ) -> RunResult:
        ctx = run.ctx
        info = error.to_info() if error is not None else error_info
        meter = ctx.meter
        end = RunEndEvent(
            status=status,
            output=output,
            error=info,
            usage=meter.usage,
            cost_usd=meter.usd if meter.cost_known or meter.usd else None,
        )
        result = await ctx.emit(HookPoint.RUN_END, end, check_deadline=False)
        if result.halted and status is RunStatus.COMPLETED:
            interrupt = ctx.interrupt(HookPoint.RUN_END, result.outcome)
            status = RunStatus.BLOCKED if isinstance(interrupt, RunBlocked) else RunStatus.ESCALATED
            output, info = None, interrupt.to_info()
        final = self._result(run, status, output=output, error=info)
        await self._store(run, status, final)
        await self._state.delete_checkpoint(ctx.run_id)
        self._close(run.channel)
        return final

    def _result(self, run: LiveRun, status: RunStatus, **fields: Any) -> RunResult:
        ctx, meter = run.ctx, run.ctx.meter
        return RunResult(
            run_id=ctx.run_id,
            task=run.record.task,
            task_version=run.record.envelope.task_version,
            status=status,
            usage=meter.usage,
            cost_usd=meter.usd if meter.cost_known or meter.usd else None,
            cost_known=meter.cost_known,
            trace=ctx.trace.events,
            started_at=run.record.created_at,
            ended_at=self._clock.now() if status.is_terminal else None,
            **fields,
        )

    async def _store(self, run: LiveRun, status: RunStatus, result: RunResult) -> None:
        run.record = run.record.model_copy(
            update={"status": status, "result": result, "updated_at": self._clock.now()}
        )
        await self._state.put_run(run.record)
        await self._event(run, "status", status=status)

    async def _set_status(self, run: LiveRun, status: RunStatus) -> None:
        if status is not run.record.status:
            run.record = run.record.model_copy(
                update={"status": status, "updated_at": self._clock.now()}
            )
            await self._state.put_run(run.record)
        await self._event(run, "status", status=status)
