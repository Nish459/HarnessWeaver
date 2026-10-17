"""What a run returns (:class:`RunResult`) and what ``harness.stream`` yields."""

from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, JsonValue

from harnessweaver.core.errors import ErrorInfo
from harnessweaver.core.messages import StreamChunk, Usage
from harnessweaver.core.runs import ApprovalRequest, RunStatus
from harnessweaver.core.trace import TraceEvent

__all__ = ["RunEvent", "RunResult"]


class RunResult(BaseModel):
    """The state of a run: its status, output or error, usage, cost and trace."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    run_id: str = Field(min_length=1)
    task: str | None = None
    task_version: str | None = None
    status: RunStatus
    output: JsonValue = None
    error: ErrorInfo | None = Field(
        default=None, description="Why the run didn't complete: failed, blocked or escalated."
    )
    approval: ApprovalRequest | None = Field(
        default=None, description="The pending approval, while awaiting_approval."
    )
    usage: Usage = Usage()
    cost_usd: float | None = Field(default=None, ge=0)
    cost_known: bool = Field(
        default=True, description="False if any model call's cost was unknown (ADR-0012)."
    )
    trace: tuple[TraceEvent, ...] = ()
    started_at: AwareDatetime | None = None
    ended_at: AwareDatetime | None = None

    @property
    def ok(self) -> bool:
        """Whether the run completed."""
        return self.status is RunStatus.COMPLETED


class RunEvent(BaseModel):
    """Progress of a run, as yielded by ``harness.stream(run_id)``.

    ``status`` and ``approval`` events are kept in the state store's event log;
    ``trace`` and ``chunk`` events are only delivered live.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    run_id: str = Field(min_length=1)
    seq: int = Field(ge=0)
    at: AwareDatetime
    type: Literal["status", "trace", "chunk", "approval"]
    status: RunStatus | None = None
    trace: TraceEvent | None = None
    chunk: StreamChunk | None = None
    approval: ApprovalRequest | None = None
