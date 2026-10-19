"""``RunContext``: one run's state and every governed operation, and the current run."""

import contextlib
from collections.abc import Generator
from contextvars import ContextVar

from harnessweaver.core.context.checks import StepChecks
from harnessweaver.core.context.models import ModelCalls
from harnessweaver.core.context.tools import ToolCalls

__all__ = ["RunContext", "current_run"]

_CURRENT: ContextVar["RunContext | None"] = ContextVar("harnessweaver_run", default=None)


def current_run() -> "RunContext | None":
    """The run active in this task, for adapters and built-in middleware."""
    return _CURRENT.get()


class RunContext(StepChecks, ModelCalls, ToolCalls):
    """The state of one run and its governed operations.

    Args:
        envelope: The run's envelope; its clock is the run's clock.
        bus: The harness's hook bus.
        trace: Where every outcome is recorded (R13).
        meter: The run's budget meter.
        models: Model access.
        tools: Tool backend.
        task: The task being run, if any.
        prompts: Where prompts come from.
        grants: Approvals already given (when resuming).
        on_chunk: Called with each streamed chunk after ``stream.chunk``.
        harness: The owning harness, for runners that build sessions.
        telemetry: Where spans and metrics go; ``None`` records none.
        can_suspend: Whether ``Suspend`` may pause this run. Standalone sessions
            can't be resumed, so there it escalates instead (DESIGNS No. 15).
    """

    @contextlib.contextmanager
    def activate(self) -> Generator["RunContext"]:
        """Make this the current run for the enclosed code (see :func:`current_run`)."""
        token = _CURRENT.set(self)
        try:
            yield self
        finally:
            _CURRENT.reset(token)
