"""HarnessWeaver: the composable AI harness framework.

Weave your own AI harness. Bring your models, choose your plugins, define
your execution.

This module is the public API (RULES C7). Everything not exported here may
change between releases.
"""

from importlib.metadata import version as _version

from harnessweaver import errors
from harnessweaver.contracts import API_VERSION
from harnessweaver.core.context import RunContext, current_run
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
from harnessweaver.core.middleware import MiddlewareDef, middleware
from harnessweaver.core.outcomes import Block, Continue, Escalate, Outcome, Retry, Suspend
from harnessweaver.core.plugins import (
    CONTRACT_VERSION,
    RESERVED_NAMESPACES,
    Plugin,
    adapter,
    decider,
    provider,
    runner,
)
from harnessweaver.core.results import RunEvent, RunResult
from harnessweaver.core.retrieval import Acl, ContextItem
from harnessweaver.core.runs import ApprovalDecision, ApprovalRequest, RunStatus
from harnessweaver.core.tools import Risk, SideEffect, ToolInfo, ToolResult
from harnessweaver.core.trace import RunTrace, TraceEvent, TraceKind
from harnessweaver.harness import Harness
from harnessweaver.session import Session
from harnessweaver.spec import EffectiveSpec, HarnessSpec, Level, ProfileSpec, load_spec

__version__: str = _version("harnessweaver")

load = Harness.load
"""Load ``harness.yaml`` and build a :class:`Harness` (same as ``Harness.load``)."""

__all__ = [
    "API_VERSION",
    "CONTRACT_VERSION",
    "RESERVED_NAMESPACES",
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
    "EffectiveSpec",
    "Envelope",
    "Escalate",
    "FakeClock",
    "Finding",
    "GuardAction",
    "GuardResult",
    "Harness",
    "HarnessSpec",
    "HookEvent",
    "HookPoint",
    "InputEvent",
    "Labels",
    "Level",
    "Message",
    "MiddlewareDef",
    "ModelRequest",
    "ModelRequestEvent",
    "ModelResponse",
    "ModelResponseEvent",
    "Outcome",
    "OutputEvent",
    "Plugin",
    "PolicyEffect",
    "Principal",
    "ProfileSpec",
    "Retry",
    "Risk",
    "Role",
    "RouteEvent",
    "RunContext",
    "RunEndEvent",
    "RunErrorEvent",
    "RunEvent",
    "RunResult",
    "RunStartEvent",
    "RunStatus",
    "RunTrace",
    "Session",
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
    "TraceEvent",
    "TraceKind",
    "Usage",
    "__version__",
    "adapter",
    "current_run",
    "decider",
    "errors",
    "format_duration",
    "load",
    "load_spec",
    "middleware",
    "parse_duration",
    "provider",
    "runner",
    "tighten",
]
