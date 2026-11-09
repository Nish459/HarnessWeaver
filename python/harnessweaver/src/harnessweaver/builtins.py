"""The core's built-in plugin.

The core registers its own runners and providers through the same
:class:`~harnessweaver.Plugin` contract third-party plugins use (ADR-0015). It owns
bare names and the reserved namespaces in ``harnessweaver.RESERVED_NAMESPACES``.
"""

from importlib.metadata import version

from harnessweaver.core.plugins import BUILTIN_NAMESPACE, Plugin
from harnessweaver.modules.approvals import (
    CallbackChannel,
    ConsoleChannel,
    EmailChannel,
    MemoryChannel,
    WebhookChannel,
)
from harnessweaver.modules.context import MemoryContext, MemoryStore, PassthroughContext
from harnessweaver.modules.evals import (
    CitationPresent,
    Contains,
    Exact,
    FieldEquals,
    GuardFired,
    LlmJudgeGrader,
    NumericClose,
    Regex,
    SchemaValid,
    Status,
)
from harnessweaver.modules.guardrails import (
    GroundedCitations,
    InjectionHeuristic,
    LlmJudge,
    PiiRegex,
    RegexDeny,
    SecretsScan,
    SizeLimit,
    TopicDeny,
)
from harnessweaver.modules.models import ScriptedModel
from harnessweaver.modules.policy import CelLitePolicy
from harnessweaver.modules.routing import (
    HashingEmbedder,
    LexicalDecider,
    LlmDecider,
    RulesDecider,
    SemanticDecider,
)
from harnessweaver.modules.state import MemoryStateStore, SqliteStateStore
from harnessweaver.runners import DirectRunner, SessionRunner, WorkflowRunner

__all__ = ["plugin"]

plugin = Plugin(
    namespace=BUILTIN_NAMESPACE,
    version=version("harnessweaver"),
    providers=[
        MemoryStateStore,
        SqliteStateStore,
        ScriptedModel,
        RegexDeny,
        PiiRegex,
        SecretsScan,
        InjectionHeuristic,
        SizeLimit,
        TopicDeny,
        LlmJudge,
        GroundedCitations,
        CelLitePolicy,
        MemoryChannel,
        CallbackChannel,
        ConsoleChannel,
        WebhookChannel,
        EmailChannel,
        RulesDecider,
        LexicalDecider,
        SemanticDecider,
        LlmDecider,
        HashingEmbedder,
        PassthroughContext,
        MemoryContext,
        MemoryStore,
        Exact,
        FieldEquals,
        NumericClose,
        Contains,
        Regex,
        SchemaValid,
        CitationPresent,
        GuardFired,
        Status,
        LlmJudgeGrader,
    ],
    runners=[DirectRunner, SessionRunner, WorkflowRunner],
    description="Runners and providers that ship with the harnessweaver core.",
)
