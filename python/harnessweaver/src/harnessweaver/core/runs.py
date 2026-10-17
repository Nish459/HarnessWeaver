"""Run status and approval contracts."""

from enum import StrEnum
from typing import Literal, Self

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, JsonValue, model_validator

from harnessweaver.core.envelope import Principal
from harnessweaver.core.messages import ToolCall
from harnessweaver.core.tools import ToolInfo

__all__ = ["ApprovalDecision", "ApprovalRequest", "RunStatus"]


class RunStatus(StrEnum):
    """Where a run is in its lifecycle (DESIGNS No. 18)."""

    PENDING = "pending"
    RUNNING = "running"
    AWAITING_APPROVAL = "awaiting_approval"
    COMPLETED = "completed"
    BLOCKED = "blocked"
    ESCALATED = "escalated"
    FAILED = "failed"
    CANCELLED = "cancelled"

    @property
    def is_terminal(self) -> bool:
        return self in _TERMINAL


_TERMINAL = frozenset(
    {
        RunStatus.COMPLETED,
        RunStatus.BLOCKED,
        RunStatus.ESCALATED,
        RunStatus.FAILED,
        RunStatus.CANCELLED,
    }
)


class ApprovalRequest(BaseModel):
    """A suspended step waiting for a human."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    approval_id: str = Field(min_length=1)
    run_id: str = Field(min_length=1)
    reason: str
    approver_role: str | None = None
    call: ToolCall | None = None
    tool: ToolInfo | None = None
    requested_at: AwareDatetime
    expires_at: AwareDatetime | None = None


class ApprovalDecision(BaseModel):
    """A human's answer to an :class:`ApprovalRequest`."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    approval_id: str = Field(min_length=1)
    decision: Literal["approve", "reject", "edit"]
    approver: Principal
    edited_args: dict[str, JsonValue] | None = None
    reason: str | None = None

    @model_validator(mode="after")
    def _check_edit(self) -> Self:
        if (self.decision == "edit") != (self.edited_args is not None):
            raise ValueError("edited_args is required for 'edit' and only allowed there")
        return self
