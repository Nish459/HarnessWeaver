"""Loading an app's effective spec: documents -> layers -> merge -> validate (DESIGNS No. 11)."""

import os
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

from pydantic import JsonValue, ValidationError

from harnessweaver.core.envelope import Budget
from harnessweaver.core.errors import BoundViolation, ExpressionSyntaxError, LevelTooLow, SpecError
from harnessweaver.core.expr import compile_expression
from harnessweaver.spec._raw import as_list, as_map
from harnessweaver.spec.explain import ExplainRow, SpecDiff, diff_data, explain_rows, origin_of
from harnessweaver.spec.levels import REQUIREMENTS, LevelReport, assess
from harnessweaver.spec.merge import (
    Bound,
    Layer,
    LayerKind,
    Lock,
    Provenance,
    check_bounds,
    merge_layers,
)
from harnessweaver.spec.models import API_VERSION, HarnessSpec, ProfileSpec
from harnessweaver.spec.paths import Item, Segment, SpecPath, format_path, parse_path
from harnessweaver.spec.sources import (
    BuiltinProfiles,
    ProfileDirectories,
    ProfileResolver,
    ResolvedProfile,
    parse_ref,
    resolve_extends,
)
from harnessweaver.spec.yaml import load_yaml_file

__all__ = [
    "ENV_VAR",
    "POLICY_VARIABLES",
    "VALIDATION_VARIABLES",
    "EffectiveSpec",
    "diff_specs",
    "load_spec",
    "spec_from_documents",
]

ENV_VAR: Final = "HARNESSWEAVER_ENV"
"""Selects the environment overlay ``harness.<env>.yaml``."""

POLICY_VARIABLES: Final = frozenset({"principal", "tenant", "task", "tool", "args", "labels"})
"""Names a ``policy.rules[].when`` expression may use."""

VALIDATION_VARIABLES: Final = frozenset({"output", "input", "task"})
"""Names a ``validation.rules[].when`` expression may use."""

_SECTIONS: Final = frozenset(
    name
    for name in ProfileSpec.model_fields
    if name not in {"api_version", "kind", "metadata", "extends", "locks", "bounds"}
)
_HARNESS_KEYS: Final = frozenset({"apiVersion", "kind", "metadata", "extends"}) | (
    _SECTIONS - {"require_level"}
)
_PROFILE_KEYS: Final = (
    frozenset({"apiVersion", "kind", "metadata", "extends", "locks", "bounds"}) | _SECTIONS
)
_OVERLAY_KEYS: Final = frozenset({"apiVersion", "kind"}) | (_SECTIONS - {"require_level"})
_BODY_EXCLUDED: Final = frozenset({"apiVersion", "kind", "metadata", "extends"})


def _check_document(document: Any, kind: str, where: str) -> dict[str, Any]:
    if not isinstance(document, dict):
        raise SpecError(f"{where} must be a YAML map")
    doc: dict[str, Any] = document  # pyright: ignore[reportUnknownVariableType]
    version = doc.get("apiVersion")
    if (kind != "Overlay" or version is not None) and version != API_VERSION:
        raise SpecError(f"{where}: apiVersion must be {API_VERSION!r}, not {version!r}")
    declared = doc.get("kind", "Overlay" if kind == "Overlay" else None)
    if declared != kind:
        raise SpecError(f"{where}: kind must be {kind!r}, not {declared!r}")
    allowed = {"Harness": _HARNESS_KEYS, "Profile": _PROFILE_KEYS, "Overlay": _OVERLAY_KEYS}[kind]
    unknown = sorted(set(doc) - allowed)
    if unknown:
        raise SpecError(
            f"{where}: unknown or misplaced key(s) {', '.join(unknown)} for a {kind} document "
            f"(allowed: {', '.join(sorted(allowed))})",
            keys=list(unknown),
        )
    if kind in {"Harness", "Profile"} and not isinstance(doc.get("metadata"), dict):
        raise SpecError(f"{where}: metadata (with at least a name) is required")
    extends = doc.get("extends", [])
    if isinstance(extends, str):
        doc = {**doc, "extends": [extends]}
    elif not (isinstance(extends, list) and all(isinstance(e, str) for e in extends)):  # pyright: ignore[reportUnknownVariableType]
        raise SpecError(f"{where}: extends must be a list of profile references")
    return doc


def _body(document: Mapping[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in document.items() if k not in _BODY_EXCLUDED}


def _loc_to_path(data: Any, loc: Sequence[int | str]) -> SpecPath:
    """Turn a Pydantic error location into a spec path, using item ids where possible."""
    path: list[Segment] = []
    node = data
    for part in loc:
        items = as_list(node)
        if isinstance(part, int) and items is not None and 0 <= part < len(items):
            entry = as_map(items[part])
            path.append(Item(str(entry.get("id", part))) if entry is not None else Item(str(part)))
            node = items[part]
        else:
            path.append(str(part))
            mapping = as_map(node)
            node = mapping.get(str(part)) if mapping is not None else None
    return tuple(path)


def _validate(data: dict[str, Any], provenance: Mapping[str, Provenance]) -> HarnessSpec:
    try:
        return HarnessSpec.model_validate(data)
    except ValidationError as exc:
        problems: list[str] = []
        for error in exc.errors():
            path = _loc_to_path(
                data, [p for p in error["loc"] if not str(p).startswith("function-")]
            )
            origin = origin_of(path, provenance)
            where = f" (from {origin.describe()})" if origin else ""
            problems.append(f"{format_path(path) or 'spec'}: {error['msg']}{where}")
        raise SpecError(
            "invalid spec:\n  " + "\n  ".join(problems), problems=list[JsonValue](problems)
        ) from None


def _compile_rule(where: str, label: str, source: str, names: frozenset[str]) -> None:
    try:
        compile_expression(source, declared=names)
    except ExpressionSyntaxError as exc:
        raise SpecError(f"{where}[{label}].when: {exc.message}", path=f"{where}[{label}]") from None


def _compile_rules(spec: HarnessSpec) -> None:
    """Compile every cel-lite rule now, so a typo fails at load rather than mid-run (R4)."""
    for index, policy_rule in enumerate(spec.policy.rules):
        label = policy_rule.id or str(index)
        _compile_rule("policy.rules", label, policy_rule.when, POLICY_VARIABLES)
    for index, validation_rule in enumerate(spec.validation.rules):
        label = validation_rule.id or str(index)
        _compile_rule("validation.rules", label, validation_rule.when, VALIDATION_VARIABLES)


def _check_bands(data: Mapping[str, Any], provenance: Mapping[str, Provenance]) -> None:
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


@dataclass(frozen=True, slots=True)
class EffectiveSpec:
    """An app's validated spec, with the layers, provenance, locks and bounds behind it."""

    spec: HarnessSpec
    data: Mapping[str, Any]
    provenance: Mapping[str, Provenance]
    locks: tuple[Lock, ...]
    bounds: tuple[Bound, ...]
    layers: tuple[Provenance, ...]
    level: LevelReport
    path: Path | None = None

    def origin(self, path: str) -> Provenance | None:
        """The layer that set ``path`` (for example ``budgets.per_run.max_usd``)."""
        return origin_of(parse_path(path), self.provenance)

    def explain(self) -> list[ExplainRow]:
        """Every effective value with its layer, lock and bounds (``spec explain``)."""
        return explain_rows(self.data, self.provenance, self.locks, self.bounds)

    def run_budget(self, task: str, overrides: Mapping[str, object] | None = None) -> Budget:
        """The budget for one run of ``task``: per-run limits, tightened by the task's own.

        ``overrides`` may only lower fields the task lists as ``overridable`` (R10).

        Raises:
            SpecError: If the task doesn't exist.
            BoundViolation: If an override isn't allowed, raises a limit, or breaks a bound.
        """
        if task not in self.spec.tasks:
            raise SpecError(f"unknown task {task!r}", task=task)
        task_spec = self.spec.tasks[task]
        budget = self.spec.budgets.per_run.intersect(task_spec.budget.to_budget())
        if not overrides:
            return budget
        for key in overrides:
            if key not in task_spec.budget.overridable:
                raise BoundViolation(
                    f"tasks.{task}.budget.{key} can't be overridden per run; "
                    f"overridable: {list(task_spec.budget.overridable)}",
                    path=f"tasks.{task}.budget.{key}",
                )
        try:
            lowered = Budget.model_validate({**budget.model_dump(), **overrides})
        except ValidationError as exc:
            raise BoundViolation(f"invalid budget override: {exc.error_count()} error(s)") from None
        for key in overrides:
            old, new = getattr(budget, key), getattr(lowered, key)
            if new is None or (old is not None and new > old):
                raise BoundViolation(
                    f"a run may only lower tasks.{task}.budget.{key} (R10)",
                    path=f"tasks.{task}.budget.{key}",
                )
        check_bounds({"budgets": {"per_run": lowered.model_dump(mode="json")}}, self.bounds, {})
        return lowered


def spec_from_documents(
    app: Mapping[str, Any],
    *,
    resolvers: Sequence[ProfileResolver] | None = None,
    overlay: Mapping[str, Any] | None = None,
    app_name: str = "harness.yaml",
    app_source: str | None = None,
    overlay_name: str | None = None,
    overlay_source: str | None = None,
    directory: Path | None = None,
) -> EffectiveSpec:
    """Build the effective spec from parsed documents.

    Raises:
        SpecError: For any invalid document, unknown profile, lock or bound
            violation, invalid expression, or a level below the required one.
    """
    app_doc = _check_document(dict(app), "Harness", app_source or app_name)
    resolvers = (
        list(resolvers) if resolvers is not None else [BuiltinProfiles(), ProfileDirectories([])]
    )
    defaults = BuiltinProfiles().resolve(parse_ref("profile://defaults"), None)
    assert defaults is not None, "the built-in defaults profile is missing"
    profiles: list[ResolvedProfile] = [
        p
        for p in resolve_extends(app_doc.get("extends", []), resolvers, directory)
        if p.layer_name != defaults.layer_name
    ]
    # Built-in profiles go before org profiles, whatever order `extends` lists them in.
    profiles.sort(key=lambda p: 0 if p.kind is LayerKind.PROFILE else 1)

    layers = [
        Layer(
            defaults.layer_name,
            defaults.kind,
            _body(_check_document(defaults.document, "Profile", defaults.layer_name)),
        )
    ]
    for profile in profiles:
        document = _check_document(
            profile.document, "Profile", profile.source or profile.layer_name
        )
        layers.append(Layer(profile.layer_name, profile.kind, _body(document), profile.source))
    layers.append(Layer(app_name, LayerKind.APP, _body(app_doc), app_source))
    if overlay is not None:
        name = overlay_name or "overlay"
        overlay_doc = _check_document(dict(overlay), "Overlay", overlay_source or name)
        layers.append(Layer(name, LayerKind.OVERLAY, _body(overlay_doc), overlay_source))

    merged = merge_layers(layers)
    data: dict[str, Any] = {
        "apiVersion": API_VERSION,
        "kind": "Harness",
        "metadata": app_doc["metadata"],
        "extends": list(app_doc.get("extends", [])),
        **merged.data,
    }
    spec = _validate(data, merged.provenance)
    _compile_rules(spec)
    _check_bands(merged.data, merged.provenance)
    level = assess(spec)
    if not level.ok:
        missing = "; ".join(REQUIREMENTS[code] for code in level.missing_for(level.required))
        raise LevelTooLow(
            f"{spec.metadata.name} reaches {level.level} but its risk tier "
            f"{spec.metadata.risk_tier!r} requires {level.required}. Missing: {missing}",
            reached=level.level.value,
            required=level.required.value,
            missing=list[JsonValue](level.missing_for(level.required)),
        )
    return EffectiveSpec(
        spec=spec,
        data=merged.data,
        provenance=merged.provenance,
        locks=tuple(merged.locks),
        bounds=tuple(merged.bounds),
        layers=tuple(merged.layers),
        level=level,
        path=Path(app_source) if app_source else None,
    )


def load_spec(
    path: str | Path,
    *,
    env: str | None = None,
    profile_dirs: Sequence[Path] = (),
    resolvers: Sequence[ProfileResolver] | None = None,
) -> EffectiveSpec:
    """Load ``harness.yaml`` with its profiles and environment overlay.

    Args:
        path: The app spec, usually ``harness.yaml``.
        env: Overlay to apply (``harness.<env>.yaml``); defaults to ``$HARNESSWEAVER_ENV``.
            A missing overlay file is not an error; ``spec explain`` lists the layers used.
        profile_dirs: Extra directories to search for ``org://`` profiles.
        resolvers: Replace the default profile resolvers entirely.

    Raises:
        SpecError: See :func:`spec_from_documents`.
    """
    path = Path(path)
    document = load_yaml_file(path)
    if not isinstance(document, dict):
        raise SpecError(f"{path} must be a YAML map")
    if resolvers is None:
        resolvers = [
            BuiltinProfiles(),
            ProfileDirectories.from_environment(path.parent, profile_dirs),
        ]
    env = env if env is not None else (os.environ.get(ENV_VAR) or None)
    overlay = None
    overlay_path = path.with_name(f"{path.stem}.{env}{path.suffix}") if env else None
    if overlay_path is not None and overlay_path.is_file():
        overlay = load_yaml_file(overlay_path)
        if not isinstance(overlay, dict):
            raise SpecError(f"{overlay_path} must be a YAML map")
    return spec_from_documents(
        document,  # pyright: ignore[reportUnknownArgumentType]
        resolvers=resolvers,
        overlay=overlay,  # pyright: ignore[reportUnknownArgumentType]
        app_name=path.name,
        app_source=str(path),
        overlay_name=overlay_path.name if overlay is not None and overlay_path else None,
        overlay_source=str(overlay_path) if overlay is not None and overlay_path else None,
        directory=path.parent,
    )


def diff_specs(before: EffectiveSpec, after: EffectiveSpec) -> SpecDiff:
    """What changes between two effective specs (``spec diff``)."""
    old_locks = {lock.text for lock in before.locks}
    new_locks = {lock.text for lock in after.locks}
    return SpecDiff(
        changes=diff_data(before.data, after.data),
        locks_added=tuple(sorted(new_locks - old_locks)),
        locks_removed=tuple(sorted(old_locks - new_locks)),
        level_before=before.level.level.value,
        level_after=after.level.level.value,
    )
