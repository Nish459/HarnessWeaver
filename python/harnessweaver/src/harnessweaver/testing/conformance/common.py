"""What every check shares: the subject under test, lifecycle order and ``expect``."""

from dataclasses import dataclass
from typing import Any, Final

from harnessweaver.core.envelope import Envelope, FakeClock
from harnessweaver.core.hooks import HookPoint
from harnessweaver.core.plugins import (
    Contribution,
)
from harnessweaver.core.registry import LoadedPlugin

__all__ = [
    "CONDITIONAL_HOOKS",
    "LATENCY_LIMITS",
    "LIFECYCLE",
    "Subject",
    "conformance_env",
    "expect",
]

LATENCY_LIMITS: Final = {"fast": 0.025, "medium": 0.25, "slow": 5.0}
"""p95 seconds allowed per declared latency class."""

LIFECYCLE: Final = (
    HookPoint.RUN_START,
    HookPoint.INPUT_BEFORE,
    HookPoint.ROUTE_DECIDE,
    HookPoint.CONTEXT_AFTER,
    HookPoint.MODEL_BEFORE,
    HookPoint.STREAM_CHUNK,
    HookPoint.MODEL_AFTER,
    HookPoint.TOOL_BEFORE,
    HookPoint.TOOL_AFTER,
    HookPoint.OUTPUT_BEFORE,
    HookPoint.APPROVAL_RESOLVED,
    HookPoint.RUN_ERROR,
    HookPoint.RUN_END,
)
"""The order hook points first fire in during one run."""

CONDITIONAL_HOOKS: Final = frozenset(
    {
        HookPoint.RUN_ERROR,
        HookPoint.APPROVAL_RESOLVED,
        HookPoint.STREAM_CHUNK,
        HookPoint.ROUTE_DECIDE,
        HookPoint.CONTEXT_AFTER,
        HookPoint.TOOL_BEFORE,
        HookPoint.TOOL_AFTER,
    }
)
"""Hooks that fire only when something specific happens, so one sample call needn't fire them."""


def expect(condition: object, message: str = "conformance check failed") -> None:
    """Fail a check. Unlike ``assert``, this still runs under ``python -O``."""
    if not condition:
        raise AssertionError(message)


def conformance_env() -> Envelope:
    return Envelope.new(tenant="conformance", principal="tester", clock=FakeClock())


@dataclass(frozen=True, slots=True)
class Subject:
    """One contribution to check, and the plugin it comes from."""

    plugin: LoadedPlugin
    contribution: Contribution

    @property
    def name(self) -> str:
        return self.contribution.name

    @property
    def item(self) -> Any:
        return self.contribution.item

    def spec(self, **sections: Any) -> dict[str, Any]:
        """A spec document that can resolve this plugin's names."""
        document = dict(sections)
        if self.plugin.source.origin == "local":
            document["plugins"] = {"local": [self.plugin.source.target]}
        return document
