"""The 13 hook points, their direction, middleware bands, and the typed event payloads.

This is HarnessWeaver's most important contract (DESIGNS No. 7). Every runner and
adapter maps its own events onto these hook points, so one middleware works
unchanged across raw SDK calls, Pydantic AI or any other framework.
"""

from collections.abc import Callable, Sequence
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue

from harnessweaver.core.decisions import Decision, DecisionRequest
from harnessweaver.core.errors import ErrorInfo
from harnessweaver.core.messages import ModelRequest, ModelResponse, StreamChunk, ToolCall, Usage
from harnessweaver.core.retrieval import ContextItem
from harnessweaver.core.runs import ApprovalDecision, ApprovalRequest, RunStatus
from harnessweaver.core.tools import ToolInfo, ToolResult

__all__ = [
    "EVENT_TYPES",
    "ApprovalResolvedEvent",
    "Band",
    "ContextEvent",
    "Direction",
    "HookEvent",
    "HookPoint",
    "InputEvent",
    "ModelRequestEvent",
    "ModelResponseEvent",
    "OutputEvent",
    "RouteEvent",
    "RunEndEvent",
    "RunErrorEvent",
    "RunStartEvent",
    "StreamChunkEvent",
    "ToolCallEvent",
    "ToolResultEvent",
    "execution_order",
]


class Direction(StrEnum):
    """Inbound hooks run outermost-first; outbound hooks run innermost-first."""

    INBOUND = "inbound"
    OUTBOUND = "outbound"


class HookPoint(StrEnum):
    """A named moment in the run lifecycle. The set is fixed and versioned (R11)."""

    RUN_START = "run.start"
    INPUT_BEFORE = "input.before"
    ROUTE_DECIDE = "route.decide"
    CONTEXT_AFTER = "context.after"
    MODEL_BEFORE = "model.before"
    MODEL_AFTER = "model.after"
    STREAM_CHUNK = "stream.chunk"
    TOOL_BEFORE = "tool.before"
    TOOL_AFTER = "tool.after"
    OUTPUT_BEFORE = "output.before"
    APPROVAL_RESOLVED = "approval.resolved"
    RUN_ERROR = "run.error"
    RUN_END = "run.end"

    @property
    def direction(self) -> Direction:
        return Direction.OUTBOUND if self in _OUTBOUND else Direction.INBOUND


_OUTBOUND = frozenset(
    {
        HookPoint.CONTEXT_AFTER,
        HookPoint.MODEL_AFTER,
        HookPoint.TOOL_AFTER,
        HookPoint.RUN_ERROR,
        HookPoint.RUN_END,
    }
)


class Band(StrEnum):
    """Middleware priority bands, outermost first.

    The spec assigns bands; a plugin can't place itself in ``baseline`` (S8).
    """

    BASELINE = "baseline"
    PLATFORM = "platform"
    APP = "app"
    TASK = "task"

    @property
    def rank(self) -> int:
        return _BAND_RANK[self]


_BAND_RANK = {Band.BASELINE: 0, Band.PLATFORM: 1, Band.APP: 2, Band.TASK: 3}


def execution_order[T](items: Sequence[T], hook: HookPoint, band: Callable[[T], Band]) -> list[T]:
    """Order middleware for one hook (fixtures suite ``hook_order``).

    ``items`` are in registration order. They are sorted by band (stable, so
    registration order holds within a band) and reversed for outbound hooks.
    """
    ordered = sorted(items, key=lambda item: band(item).rank)
    if hook.direction is Direction.OUTBOUND:
        ordered.reverse()
    return ordered


# --- Event payloads ------------------------------------------------------------------------
# Payloads carry raw content in process. Telemetry must never record it before
# redaction (R9).


class _Event(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class RunStartEvent(_Event):
    hook: Literal["run.start"] = "run.start"
    task: str | None = None
    input: JsonValue = None


class InputEvent(_Event):
    hook: Literal["input.before"] = "input.before"
    input: JsonValue


class RouteEvent(_Event):
    hook: Literal["route.decide"] = "route.decide"
    request: DecisionRequest
    decision: Decision | None = Field(
        default=None, description="Set by the middleware (usually routing) that decides."
    )


class ContextEvent(_Event):
    hook: Literal["context.after"] = "context.after"
    source: str
    query: str | None = None
    items: tuple[ContextItem, ...] = ()


class ModelRequestEvent(_Event):
    hook: Literal["model.before"] = "model.before"
    request: ModelRequest


class ModelResponseEvent(_Event):
    hook: Literal["model.after"] = "model.after"
    request: ModelRequest
    response: ModelResponse


class StreamChunkEvent(_Event):
    hook: Literal["stream.chunk"] = "stream.chunk"
    request: ModelRequest
    chunk: StreamChunk
    text_so_far: str = ""


class ToolCallEvent(_Event):
    hook: Literal["tool.before"] = "tool.before"
    call: ToolCall
    tool: ToolInfo
    approval: ApprovalDecision | None = Field(
        default=None,
        description="A human's approval of this call. Re-check edited args; don't ask again.",
    )


class ToolResultEvent(_Event):
    hook: Literal["tool.after"] = "tool.after"
    call: ToolCall
    tool: ToolInfo
    result: ToolResult


class OutputEvent(_Event):
    hook: Literal["output.before"] = "output.before"
    output: JsonValue
    attempt: int = Field(default=0, ge=0, description="0 for the first answer, then repairs.")
    schema_name: str | None = None
    approval: ApprovalDecision | None = Field(
        default=None, description="A human's approval of this output; don't ask again."
    )


class ApprovalResolvedEvent(_Event):
    hook: Literal["approval.resolved"] = "approval.resolved"
    request: ApprovalRequest
    decision: ApprovalDecision


class RunErrorEvent(_Event):
    hook: Literal["run.error"] = "run.error"
    error: ErrorInfo
    step: str | None = None


class RunEndEvent(_Event):
    hook: Literal["run.end"] = "run.end"
    status: RunStatus
    output: JsonValue = None
    error: ErrorInfo | None = None
    usage: Usage = Usage()
    cost_usd: float | None = Field(default=None, ge=0)


HookEvent = Annotated[
    RunStartEvent
    | InputEvent
    | RouteEvent
    | ContextEvent
    | ModelRequestEvent
    | ModelResponseEvent
    | StreamChunkEvent
    | ToolCallEvent
    | ToolResultEvent
    | OutputEvent
    | ApprovalResolvedEvent
    | RunErrorEvent
    | RunEndEvent,
    Field(discriminator="hook"),
]
"""Any hook event, discriminated by its ``hook`` field."""

EVENT_TYPES: dict[HookPoint, type[_Event]] = {
    HookPoint.RUN_START: RunStartEvent,
    HookPoint.INPUT_BEFORE: InputEvent,
    HookPoint.ROUTE_DECIDE: RouteEvent,
    HookPoint.CONTEXT_AFTER: ContextEvent,
    HookPoint.MODEL_BEFORE: ModelRequestEvent,
    HookPoint.MODEL_AFTER: ModelResponseEvent,
    HookPoint.STREAM_CHUNK: StreamChunkEvent,
    HookPoint.TOOL_BEFORE: ToolCallEvent,
    HookPoint.TOOL_AFTER: ToolResultEvent,
    HookPoint.OUTPUT_BEFORE: OutputEvent,
    HookPoint.APPROVAL_RESOLVED: ApprovalResolvedEvent,
    HookPoint.RUN_ERROR: RunErrorEvent,
    HookPoint.RUN_END: RunEndEvent,
}
"""The payload type each hook point carries."""
