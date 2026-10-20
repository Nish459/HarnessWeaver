"""HarnessWeaver: the composable AI harness framework.

Weave your own AI harness. Bring your models, choose your plugins, define
your execution.

This module is the public API (RULES C7). Everything not exported here may
change between releases.
"""

from importlib.metadata import version as _version

from loguru import logger as _logger

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
from harnessweaver.core.evals import (
    Baseline,
    CaseResult,
    EvalCase,
    EvalDataset,
    EvalSample,
    Grade,
    GraderResult,
    GuardFiring,
    OnlineSample,
    ShadowGuardReport,
    SuiteResult,
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
from harnessweaver.core.manifests import ToolManifest, definition_digest
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
from harnessweaver.core.policy import (
    PolicyCase,
    PolicyConfig,
    PolicyDecision,
    PolicyRequest,
    PolicyRule,
    PolicyTests,
    decide_by_rules,
)
from harnessweaver.core.replay import ReplayReport, TraceChange
from harnessweaver.core.results import RunEvent, RunResult
from harnessweaver.core.retrieval import Acl, ContextItem
from harnessweaver.core.runs import ApprovalDecision, ApprovalRequest, RunStatus
from harnessweaver.core.tools import (
    Risk,
    SandboxLimits,
    SandboxResult,
    SideEffect,
    ToolInfo,
    ToolResult,
    ToolVerdict,
)
from harnessweaver.core.trace import RunTrace, TraceEvent, TraceKind
from harnessweaver.harness import Harness
from harnessweaver.session import Session
from harnessweaver.spec import EffectiveSpec, HarnessSpec, Level, ProfileSpec, load_spec

# A library stays silent until the app opts in with logger.enable("harnessweaver"),
# as loguru recommends for libraries (ADR-0024).
_logger.disable(__name__)

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
    "Baseline",
    "Block",
    "Budget",
    "CaseResult",
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
    "EvalCase",
    "EvalDataset",
    "EvalSample",
    "FakeClock",
    "Finding",
    "Grade",
    "GraderResult",
    "GuardAction",
    "GuardFiring",
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
    "OnlineSample",
    "Outcome",
    "OutputEvent",
    "Plugin",
    "PolicyCase",
    "PolicyConfig",
    "PolicyDecision",
    "PolicyEffect",
    "PolicyRequest",
    "PolicyRule",
    "PolicyTests",
    "Principal",
    "ProfileSpec",
    "ReplayReport",
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
    "SandboxLimits",
    "SandboxResult",
    "Session",
    "ShadowGuardReport",
    "SideEffect",
    "StreamChunk",
    "StreamChunkEvent",
    "SuiteResult",
    "Suspend",
    "SystemClock",
    "ToolCall",
    "ToolCallEvent",
    "ToolInfo",
    "ToolManifest",
    "ToolResult",
    "ToolResultEvent",
    "ToolSpec",
    "ToolVerdict",
    "TraceChange",
    "TraceEvent",
    "TraceKind",
    "Usage",
    "__version__",
    "adapter",
    "current_run",
    "decide_by_rules",
    "decider",
    "definition_digest",
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
