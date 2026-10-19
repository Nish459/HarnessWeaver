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
    MemoryChannel,
    WebhookChannel,
)
from harnessweaver.modules.guardrails import (
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
        CelLitePolicy,
        MemoryChannel,
        CallbackChannel,
        ConsoleChannel,
        WebhookChannel,
    ],
    runners=[DirectRunner, SessionRunner, WorkflowRunner],
    description="Runners and providers that ship with the harnessweaver core.",
)
