"""Load-time checks on the validated spec: rules, bands, sidecar guards, plugin profiles (R4)."""

from collections.abc import Mapping, Sequence
from typing import Any, Final

from harnessweaver.core.errors import (
    ExpressionSyntaxError,
    PluginNotAllowed,
    SpecError,
)
from harnessweaver.core.expr import compile_expression
from harnessweaver.core.plugins import RESERVED_NAMESPACES
from harnessweaver.core.policy import RUN_POLICY_VARIABLES, TOOL_POLICY_VARIABLES
from harnessweaver.spec._raw import as_list, as_map
from harnessweaver.spec.merge import (
    Lock,
    Provenance,
)
from harnessweaver.spec.merge.layers import item_id
from harnessweaver.spec.models import HarnessSpec
from harnessweaver.spec.paths import Item, SpecPath, format_path, is_prefix

__all__ = [
    "POLICY_VARIABLES",
    "VALIDATION_VARIABLES",
    "check_bands",
    "check_plugin_profiles",
    "check_sidecar_guards",
    "compile_rules",
]

POLICY_VARIABLES: Final = TOOL_POLICY_VARIABLES
"""Names a ``tool.before`` ``policy.rules[].when`` may use (``run.start`` rules: fewer)."""

VALIDATION_VARIABLES: Final = frozenset({"output", "input", "task"})
"""Names a ``validation.rules[].when`` expression may use."""


def _compile_rule(where: str, label: str, source: str, names: frozenset[str]) -> None:
    try:
        compile_expression(source, declared=names)
    except ExpressionSyntaxError as exc:
        raise SpecError(f"{where}[{label}].when: {exc.message}", path=f"{where}[{label}]") from None


def compile_rules(spec: HarnessSpec) -> None:
    """Compile every cel-lite rule now, so a typo fails at load rather than mid-run (R4)."""
    # Other engines (cel.policy) compile their own rules when they're built.
    if spec.policy.use == "cel_lite":
        for index, policy_rule in enumerate(spec.policy.rules):
            label = policy_rule.id or str(index)
            names = POLICY_VARIABLES if policy_rule.hook == "tool.before" else RUN_POLICY_VARIABLES
            _compile_rule("policy.rules", label, policy_rule.when, names)
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


def check_sidecar_guards(data: Mapping[str, Any], locks: Sequence[Lock]) -> None:
    """A locked guard that runs on the sidecar is only as fixed as ``sidecar.url`` (R1).

    The URL is a separate value, so without a lock of its own a later layer could point
    the guard at a server that allows everything, with the guard's lock intact. An
    unlocked guard needs no such lock: a later layer could just switch it off.

    Raises:
        SpecError: If an enabled ``where: sidecar`` guard is locked and the URL isn't.
    """
    if any(is_prefix(lock.path, ("sidecar", "url")) for lock in locks):
        return
    sections: list[tuple[SpecPath, Any]] = [(("guardrails",), data.get("guardrails"))]
    for name, task in (as_map(data.get("tasks")) or {}).items():
        sections.append(
            (("tasks", str(name), "guardrails"), (as_map(task) or {}).get("guardrails"))
        )
    for prefix, section in sections:
        for stage, items in (as_map(section) or {}).items():
            for raw in as_list(items) or []:
                guard = as_map(raw) or {}
                if guard.get("where") != "sidecar" or guard.get("enabled") is False:
                    continue
                path: SpecPath = (*prefix, str(stage), Item(item_id(guard)))
                # A lock on the guard, on something above it or on one of its fields.
                if any(is_prefix(lock.path[: len(path)], path) for lock in locks):
                    where = format_path(path)
                    raise SpecError(
                        f"{where} is locked and runs on the sidecar, so sidecar.url must be "
                        f"locked too, or a later layer could repoint it (R1)",
                        path=where,
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
