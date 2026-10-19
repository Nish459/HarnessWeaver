"""Load-time checks on the validated spec: rules compile, bands and plugin profiles (R4)."""

from collections.abc import Mapping, Sequence
from typing import Any, Final

from harnessweaver.core.errors import (
    ExpressionSyntaxError,
    PluginNotAllowed,
    SpecError,
)
from harnessweaver.core.expr import compile_expression
from harnessweaver.core.plugins import RESERVED_NAMESPACES
from harnessweaver.spec._raw import as_list, as_map
from harnessweaver.spec.merge import (
    Provenance,
)
from harnessweaver.spec.models import HarnessSpec

__all__ = [
    "POLICY_VARIABLES",
    "VALIDATION_VARIABLES",
    "check_bands",
    "check_plugin_profiles",
    "compile_rules",
]

POLICY_VARIABLES: Final = frozenset({"principal", "tenant", "task", "tool", "args", "labels"})
"""Names a ``policy.rules[].when`` expression may use."""

VALIDATION_VARIABLES: Final = frozenset({"output", "input", "task"})
"""Names a ``validation.rules[].when`` expression may use."""


def _compile_rule(where: str, label: str, source: str, names: frozenset[str]) -> None:
    try:
        compile_expression(source, declared=names)
    except ExpressionSyntaxError as exc:
        raise SpecError(f"{where}[{label}].when: {exc.message}", path=f"{where}[{label}]") from None


def compile_rules(spec: HarnessSpec) -> None:
    """Compile every cel-lite rule now, so a typo fails at load rather than mid-run (R4)."""
    for index, policy_rule in enumerate(spec.policy.rules):
        label = policy_rule.id or str(index)
        _compile_rule("policy.rules", label, policy_rule.when, POLICY_VARIABLES)
    for index, validation_rule in enumerate(spec.validation.rules):
        label = validation_rule.id or str(index)
        _compile_rule("validation.rules", label, validation_rule.when, VALIDATION_VARIABLES)


def check_bands(data: Mapping[str, Any], provenance: Mapping[str, Provenance]) -> None:
    for raw in as_list(data.get("middleware")) or []:
        item = as_map(raw)
        if item is not None and item.get("band") == "baseline":
            key = f"middleware[{item.get('id')}].band"
            origin = provenance.get(key)
            if origin is None or not origin.kind.is_profile:
                who = origin.describe() if origin else "an app layer"
                raise SpecError(
                    f"{key}: only profiles may put middleware in the baseline band, "
                    f"but {who} does (RULES S8)",
                    path=key,
                )


def check_plugin_profiles(spec: HarnessSpec, layers: Sequence[Provenance]) -> None:
    """Plugin profiles count as using the plugin, so ``plugins.allow`` applies (S8)."""
    allow = spec.plugins.allow
    if allow is None:
        return
    for layer in layers:
        if layer.layer.startswith("profile://") and "." in layer.layer:
            namespace = layer.layer.removeprefix("profile://").split(".", 1)[0]
            if namespace not in RESERVED_NAMESPACES and namespace not in allow:
                raise PluginNotAllowed(
                    f"{layer.layer} comes from plugin {namespace!r}, which isn't in "
                    f"plugins.allow ({', '.join(sorted(allow)) or '(none)'})",
                    namespace=namespace,
                )
