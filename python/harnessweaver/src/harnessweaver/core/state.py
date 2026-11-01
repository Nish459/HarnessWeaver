"""What a ``StateStore`` keeps: run records, checkpoints, approval grants (DESIGNS No. 18).

A checkpoint is written when a run suspends for approval. It holds everything
needed to resume the run, possibly in another process: the runner's resume
point, the budget meter, labels, the pending approval and the approvals granted
so far.
"""

from datetime import timedelta
from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, JsonValue

from harnessweaver.core.digests import canonical_digest
from harnessweaver.core.envelope import Envelope, Labels
from harnessweaver.core.messages import ModelRequest, ModelResponse, ToolCall, Usage
from harnessweaver.core.results import RunResult
from harnessweaver.core.runs import ApprovalDecision, ApprovalRequest, RunStatus
from harnessweaver.core.tools import ToolResult

__all__ = [
    "Checkpoint",
    "Grant",
    "MeterSnapshot",
    "RecordedCall",
    "RunRecord",
    "call_digest",
    "output_digest",
    "request_digest",
]


def call_digest(call: ToolCall) -> str:
    """Identify a tool call by name and arguments, ignoring its id (ids change on re-runs)."""
    return canonical_digest({"name": call.name, "arguments": call.arguments})


def output_digest(output: JsonValue) -> str:
    """Identify a candidate output."""
    return canonical_digest({"output": output})


def request_digest(request: ModelRequest) -> str:
    """Identify what a model was asked; request metadata isn't part of it."""
    return canonical_digest({"request": request.model_dump(mode="json", exclude={"metadata"})})


class _Record(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class Grant(_Record):
    """An approval a human gave. A matching output passes without asking again, and so does
    a matching call: once, unless ``approvals.grant_scope`` is ``run`` (ADR-0045)."""

    hook: Literal["tool.before", "output.before"]
    digest: str = Field(description="call_digest of the original call, or output_digest.")
    decision: ApprovalDecision


class MeterSnapshot(_Record):
    """A budget meter's usage, so a resumed run keeps counting from where it was."""

    usd: float = Field(default=0.0, ge=0)
    cost_known: bool = True
    usage: Usage = Usage()
    model_calls: int = Field(default=0, ge=0)
    tool_calls: int = Field(default=0, ge=0)


class RunRecord(_Record):
    """A run as the state store keeps it."""

    run_id: str = Field(min_length=1)
    tenant: str = Field(min_length=1)
    task: str | None = None
    status: RunStatus
    envelope: Envelope
    input: JsonValue = None
    result: RunResult | None = None
    created_at: AwareDatetime
    updated_at: AwareDatetime


class Checkpoint(_Record):
    """Everything needed to resume a suspended run."""

    run_id: str = Field(min_length=1)
    task: str | None = None
    input: JsonValue = Field(default=None, description="The input after input.before.")
    resume: dict[str, JsonValue] = Field(
        default_factory=dict[str, JsonValue], description="The runner's resume point."
    )
    meter: MeterSnapshot = MeterSnapshot()
    labels: Labels = Labels()
    grants: tuple[Grant, ...] = ()
    approval: ApprovalRequest | None = Field(
        default=None, description="The pending approval; cleared once a human answers."
    )
    approval_hook: Literal["tool.before", "output.before"] | None = None
    approval_digest: str | None = Field(
        default=None, description="What the approval covers: call_digest or output_digest."
    )
    approval_args: dict[str, JsonValue] | None = Field(
        default=None, description="Arguments an earlier answer chose, which this one inherits."
    )
    time_left: timedelta | None = Field(
        default=None, description="Deadline time left at suspension; waiting doesn't count."
    )
    context_ids: tuple[str, ...] = Field(
        default=(), description="Ids of the context items the run kept, for citation checks."
    )


class RecordedCall(_Record):
    """What a recorded run got from outside: a model's answer, a tool's result, or a
    human's approval, in order (``state.record: true``, ADR-0035).

    ``harnessweaver replay`` feeds these back to the run instead of calling out.
    Unlike traces, recordings hold content: the state store keeps them like it
    keeps a run's input, and they are off unless the spec turns them on (R9).
    """

    run_id: str = Field(min_length=1)
    seq: int = Field(ge=0)
    kind: Literal["model", "tool", "approval"]
    digest: str = Field(
        description="model: request_digest of the request; tool: call_digest; "
        "approval: call_digest or output_digest of what it covers."
    )
    response: ModelResponse | None = None
    result: ToolResult | None = None
    hook: Literal["tool.before", "output.before"] | None = None
    decision: ApprovalDecision | None = None
