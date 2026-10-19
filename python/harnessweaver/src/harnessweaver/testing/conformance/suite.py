"""Which checks apply to which contribution."""

from typing import Final

from harnessweaver.core.middleware import MiddlewareDef
from harnessweaver.core.plugins import (
    AdapterInfo,
    ProviderInfo,
    RunnerInfo,
)
from harnessweaver.core.registry import LoadedPlugin
from harnessweaver.testing.conformance.builds import check_builds
from harnessweaver.testing.conformance.common import Subject
from harnessweaver.testing.conformance.hooks import check_adapter, check_middleware, check_runner
from harnessweaver.testing.conformance.observability import check_latency, check_no_raw_content
from harnessweaver.testing.conformance.results import (
    check_deterministic,
    check_results,
    check_timeout_blocks,
)

__all__ = ["CHECKS", "applies", "subjects"]

CHECKS: Final = (
    ("builds", check_builds),
    ("results", check_results),
    ("deterministic", check_deterministic),
    ("timeout", check_timeout_blocks),
    ("no_raw_content", check_no_raw_content),
    ("latency", check_latency),
    ("middleware", check_middleware),
    ("runner", check_runner),
    ("adapter", check_adapter),
)
"""Each contribution check, by name."""


def applies(check: str, subject: Subject) -> bool:
    """Whether ``check`` has anything to verify for ``subject``."""
    item = subject.item
    if check == "builds":
        return True
    if isinstance(item, ProviderInfo):
        if check == "results":
            return True
        if check == "deterministic":
            return item.deterministic and item.port in (
                "Guardrail",
                "Decider",
                "ModelProvider",
                "PolicyEngine",
                "Embedder",
            )
        if check == "timeout":
            return item.port == "Guardrail"
        if check == "no_raw_content":
            return item.port in ("Guardrail", "ModelProvider")
        if check == "latency":
            return item.port in (
                "Guardrail",
                "Decider",
                "ModelProvider",
                "StateStore",
                "PolicyEngine",
            )
        return False
    return (
        (check == "middleware" and isinstance(item, MiddlewareDef))
        or (check == "runner" and isinstance(item, RunnerInfo))
        or (check == "adapter" and isinstance(item, AdapterInfo))
    )


def subjects(loaded: LoadedPlugin) -> list[Subject]:
    """Every contribution of ``loaded``, ready to check."""
    return [Subject(loaded, contribution) for contribution in loaded.plugin.contributions()]
