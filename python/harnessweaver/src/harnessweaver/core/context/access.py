"""What a run is given: model access, task info, tools, prompts and pending approvals."""

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Protocol

from pydantic import JsonValue

from harnessweaver.core.budgets import PriceLookup
from harnessweaver.core.envelope import Envelope
from harnessweaver.core.errors import (
    SpecError,
)
from harnessweaver.core.hooks import (
    HookPoint,
)
from harnessweaver.core.messages import ToolCall
from harnessweaver.core.ports import (
    ModelProvider,
    ToolDescription,
)
from harnessweaver.core.tools import ToolInfo, ToolResult

__all__ = [
    "MODEL_RETRIES",
    "SUSPENDABLE_HOOKS",
    "ModelAccess",
    "NoTools",
    "PendingApproval",
    "PromptSource",
    "TaskInfo",
]

MODEL_RETRIES = 1
"""How many times a ``Retry`` at ``model.after`` may re-ask the model."""

SUSPENDABLE_HOOKS = frozenset({HookPoint.TOOL_BEFORE, HookPoint.OUTPUT_BEFORE})
"""Where ``Suspend`` pauses for approval. Elsewhere it escalates (DESIGNS No. 18)."""


class PromptSource(Protocol):
    """Renders versioned prompts (ADR-0013)."""

    async def render(self, ref: str, variables: Mapping[str, Any]) -> str: ...


@dataclass(frozen=True, slots=True)
class ModelAccess:
    """How a run reaches models: the provider, aliases and prices (DESIGNS No. 16)."""

    provider: ModelProvider | None = None
    default_alias: str | None = None
    aliases: Mapping[str, str] = field(default_factory=dict[str, str])
    allowed_aliases: frozenset[str] | None = None
    prices: PriceLookup | None = None
    provider_name: str | None = None
    """For telemetry: ``gen_ai.provider.name``, e.g. ``openai`` or ``anthropic``."""


@dataclass(frozen=True, slots=True)
class TaskInfo:
    """The parts of a task a runner needs, without the spec types."""

    name: str
    version: str = "1.0.0"
    approver_role: str | None = None
    """Who approves when the step that asks names nobody: the task's role, else the spec's."""
    model: str | None = None
    prompt: str | None = None
    tools: tuple[str, ...] = ()
    input_type: type[Any] | None = None
    output_type: type[Any] | None = None
    """A Pydantic model, ``str``, or ``None`` for whatever the model returns."""
    max_repairs: int = 1
    on_failure: str = "block"


class NoTools:
    """The tool backend when none is configured: every tool is unknown."""

    def describe(self, name: str) -> ToolDescription | None:
        return None

    async def execute(self, call: ToolCall, env: Envelope) -> ToolResult:  # pragma: no cover
        raise SpecError(f"no tool backend is configured for {call.name!r}")


@dataclass(frozen=True, slots=True)
class PendingApproval:
    """What a ``Suspend`` paused on, so the harness can ask a human and resume."""

    hook: HookPoint
    reason: str
    approver_role: str | None
    digest: str
    call: ToolCall | None = None
    tool: ToolInfo | None = None
    edited_args: dict[str, JsonValue] | None = None
    """Arguments an earlier answer chose, when this asks again about the same call."""
