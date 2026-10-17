"""HarnessWeaver: the composable AI harness framework.

Weave your own AI harness. Bring your models, choose your plugins, define
your execution.

This module is the public API (RULES C7). Everything not exported here may
change between releases.
"""

from importlib.metadata import version as _version

from harnessweaver import errors
from harnessweaver.contracts import API_VERSION
from harnessweaver.core.decisions import (
    Decision,
    DecisionKind,
    DecisionRequest,
    PolicyEffect,
    tighten,
)
from harnessweaver.core.durations import Duration, format_duration, parse_duration
from harnessweaver.core.envelope import (
    Budget,
    Clock,
    Envelope,
    FakeClock,
    Labels,
    Principal,
    SystemClock,
)
from harnessweaver.core.guards import Finding, GuardAction, GuardResult
from harnessweaver.core.hooks import (
    ApprovalResolvedEvent,
    Band,
    ContextEvent,
    Direction,
    HookEvent,
    HookPoint,
    InputEvent,
    ModelRequestEvent,
    ModelResponseEvent,
    OutputEvent,
    RouteEvent,
    RunEndEvent,
    RunErrorEvent,
    RunStartEvent,
    StreamChunkEvent,
    ToolCallEvent,
    ToolResultEvent,
)
from harnessweaver.core.messages import (
    Message,
    ModelRequest,
    ModelResponse,
    Role,
    StreamChunk,
    ToolCall,
    ToolSpec,
    Usage,
)
from harnessweaver.core.outcomes import Block, Continue, Escalate, Outcome, Retry, Suspend
from harnessweaver.core.retrieval import Acl, ContextItem
from harnessweaver.core.runs import ApprovalDecision, ApprovalRequest, RunStatus
from harnessweaver.core.tools import Risk, SideEffect, ToolInfo, ToolResult

__version__: str = _version("harnessweaver")

__all__ = [
    "API_VERSION",
    "Acl",
    "ApprovalDecision",
    "ApprovalRequest",
    "ApprovalResolvedEvent",
    "Band",
    "Block",
    "Budget",
    "Clock",
    "ContextEvent",
    "ContextItem",
    "Continue",
    "Decision",
    "DecisionKind",
    "DecisionRequest",
    "Direction",
    "Duration",
    "Envelope",
    "Escalate",
    "FakeClock",
    "Finding",
    "GuardAction",
    "GuardResult",
    "HookEvent",
    "HookPoint",
    "InputEvent",
    "Labels",
    "Message",
    "ModelRequest",
    "ModelRequestEvent",
    "ModelResponse",
    "ModelResponseEvent",
    "Outcome",
    "OutputEvent",
    "PolicyEffect",
    "Principal",
    "Retry",
    "Risk",
    "Role",
    "RouteEvent",
    "RunEndEvent",
    "RunErrorEvent",
    "RunStartEvent",
    "RunStatus",
    "SideEffect",
    "StreamChunk",
    "StreamChunkEvent",
    "Suspend",
    "SystemClock",
    "ToolCall",
    "ToolCallEvent",
    "ToolInfo",
    "ToolResult",
    "ToolResultEvent",
    "ToolSpec",
    "Usage",
    "__version__",
    "errors",
    "format_duration",
    "parse_duration",
    "tighten",
]
