"""What ``harnessweaver replay`` reports about a recorded run (ADR-0035)."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from harnessweaver.core.hooks import HookPoint
from harnessweaver.core.outcomes import OutcomeKind
from harnessweaver.core.results import RunResult

__all__ = ["ReplayReport", "TraceChange"]


class TraceChange(BaseModel):
    """A decision one run's trace has and the other's doesn't."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    change: Literal["added", "removed"] = Field(description="added: only the replay has it.")
    hook: HookPoint | None = None
    source: str
    outcome: OutcomeKind | None = None
    code: str | None = None
    reason: str | None = None


class ReplayReport(BaseModel):
    """A recorded run, run again against the current code and spec."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    run_id: str = Field(min_length=1, description="The recorded run.")
    task: str = Field(min_length=1)
    original: RunResult
    replayed: RunResult
    same_status: bool
    same_output: bool
    changes: tuple[TraceChange, ...] = Field(
        default=(),
        description="Decisions (outcomes other than a plain continue, coded notes) "
        "that differ, in trace order.",
    )
    model_answers: int = Field(ge=0, description="Model answers in the recording.")
    model_answers_used: int = Field(ge=0)
    changed_requests: int = Field(
        ge=0, description="Model calls whose request differs from the recorded one."
    )
    missing_tool_results: int = Field(
        ge=0, description="Tool calls the recording has no result for; they failed."
    )

    @property
    def differs(self) -> bool:
        """Whether the status or the output changed."""
        return not (self.same_status and self.same_output)
