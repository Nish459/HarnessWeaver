"""Contract constants and the rules for contributed names (DESIGNS No. 13)."""

import re
from typing import Final

from harnessweaver.core.semver import Version, VersionRange

__all__ = [
    "BUILTIN_NAMESPACE",
    "CONTRACT_VERSION",
    "DEFAULT_CONTRACT",
    "ENTRY_POINT_GROUP",
    "LATENCY_CLASSES",
    "NAMESPACE_PATTERN",
    "PORTS",
    "RESERVED_NAMESPACES",
    "check_name",
    "namespace_of",
    "parse_contract",
    "qualify",
]

CONTRACT_VERSION: Final = Version(1, 0, 0)
"""The version of the ``harnessweaver/v1`` contract this core implements (V5)."""

ENTRY_POINT_GROUP: Final = "harnessweaver.plugins"
"""Installed plugins expose their ``Plugin`` object in this entry-point group."""

BUILTIN_NAMESPACE: Final = "harnessweaver"
"""The namespace of the core's own built-in plugin."""

RESERVED_NAMESPACES: Final = frozenset(
    {
        BUILTIN_NAMESPACE,
        # runners
        "direct",
        "session",
        "workflow",
        # models, state, approvals, context
        "scripted",
        "memory",
        "sqlite",
        "callback",
        "console",
        "webhook",
        "email",
        "passthrough",
        # policy, routing, validation
        "cel_lite",
        "rules",
        "lexical",
        "semantic",
        "llm",
        "pydantic",
        "json_schema",
        # guardrails
        "pii",
        "secrets",
        "regex",
        "injection",
        "size",
        "topic",
        "grounded",
        # evals
        "exact",
        "contains",
        "schema_valid",
        "field_equals",
        "numeric_close",
        "citation_present",
        "guard_fired",
        "status",
        "llm_judge",
    }
)
"""Namespaces owned by the built-in plugin. Bare names (``direct``) are their own
namespace. Other plugins can't claim these (DESIGNS No. 13)."""

PORTS: Final = frozenset(
    {
        "ApprovalChannel",
        "ContextProvider",
        "Decider",
        "Embedder",
        "Evaluator",
        "Guardrail",
        "Memory",
        "ModelProvider",
        "PolicyEngine",
        "Sandbox",
        "StateStore",
        "Telemetry",
    }
)
"""The ports a provider can implement (DESIGNS No. 14). A port is listed only when the
harness looks its providers up by name, so a declared provider never sits unused. A
planned port joins when that lookup exists; ``ToolGovernor`` never does, because the
governor enforces the baseline and a spec must not swap it out (R1)."""

LATENCY_CLASSES: Final = ("fast", "medium", "slow")
"""Declared latency classes; the conformance suite checks p95 against them."""

NAMESPACE_PATTERN = re.compile(r"^[a-z][a-z0-9_]*$")
_NAME = re.compile(r"^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)*$")
DEFAULT_CONTRACT: Final = ">=1.0,<2"


def namespace_of(name: str) -> str:
    """The namespace a name belongs to: the text before the first dot, or the bare name."""
    return name.split(".", 1)[0]


def qualify(namespace: str, name: str) -> str:
    """Give a bare contributed name its plugin's namespace.

    The built-in plugin keeps its names as written: they are bare or in a
    reserved namespace.
    """
    if namespace == BUILTIN_NAMESPACE or "." in name:
        return name
    return f"{namespace}.{name}"


def parse_contract(text: str) -> VersionRange:
    try:
        return VersionRange.parse(text)
    except ValueError as exc:
        raise ValueError(f"invalid contract range {text!r}: {exc}") from None


def check_name(name: str) -> str:
    if not _NAME.match(name):
        raise ValueError(f"invalid name {name!r}: use lowercase words joined by dots")
    return name
