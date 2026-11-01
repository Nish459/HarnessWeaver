"""``load_spec`` and ``spec_from_documents``: from files to an ``EffectiveSpec``."""

import os
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, Final

from pydantic import JsonValue

from harnessweaver.core.errors import (
    LevelTooLow,
    SpecError,
)
from harnessweaver.core.registry import PluginCatalog
from harnessweaver.spec.explain import SpecDiff, diff_data
from harnessweaver.spec.levels import REQUIREMENTS, assess
from harnessweaver.spec.loader.checks import (
    check_bands,
    check_plugin_profiles,
    check_sidecar_guards,
    compile_rules,
)
from harnessweaver.spec.loader.documents import check_document, layer_body, validate_spec
from harnessweaver.spec.loader.effective import EffectiveSpec
from harnessweaver.spec.merge import (
    Layer,
    LayerKind,
    merge_layers,
)
from harnessweaver.spec.models import API_VERSION
from harnessweaver.spec.sources import (
    BuiltinProfiles,
    PluginProfiles,
    ProfileDirectories,
    ProfileResolver,
    ResolvedProfile,
    parse_ref,
    resolve_extends,
)
from harnessweaver.spec.yaml import load_yaml_file

__all__ = ["ENV_VAR", "diff_specs", "load_spec", "spec_from_documents"]

ENV_VAR: Final = "HARNESSWEAVER_ENV"
"""Selects the environment overlay ``harness.<env>.yaml``."""


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
    app_doc = check_document(dict(app), "Harness", app_source or app_name)
    resolvers = (
        list(resolvers)
        if resolvers is not None
        else [BuiltinProfiles(), PluginProfiles(PluginCatalog.default()), ProfileDirectories([])]
    )
    defaults = BuiltinProfiles().resolve(parse_ref("profile://defaults"), None)
    assert defaults is not None, "the built-in defaults profile is missing"
    profiles: list[ResolvedProfile] = [
        p
        for p in resolve_extends(app_doc.get("extends", []), resolvers, directory)
        if p.layer_name != defaults.layer_name
    ]
    # Built-in profiles, then the platform's, then the app's own, whatever order `extends`
    # lists them in: a layer's locks bind only later layers, so the app's profiles must
    # come after the locks that are meant to bind them (R1, ADR-0043).
    profiles.sort(key=lambda p: 0 if p.kind is LayerKind.PROFILE else 2 if p.app_owned else 1)

    layers = [
        Layer(
            defaults.layer_name,
            defaults.kind,
            layer_body(check_document(defaults.document, "Profile", defaults.layer_name)),
        )
    ]
    for profile in profiles:
        document = check_document(profile.document, "Profile", profile.source or profile.layer_name)
        layers.append(Layer(profile.layer_name, profile.kind, layer_body(document), profile.source))
    layers.append(Layer(app_name, LayerKind.APP, layer_body(app_doc), app_source))
    if overlay is not None:
        name = overlay_name or "overlay"
        overlay_doc = check_document(dict(overlay), "Overlay", overlay_source or name)
        layers.append(Layer(name, LayerKind.OVERLAY, layer_body(overlay_doc), overlay_source))

    merged = merge_layers(layers)
    data: dict[str, Any] = {
        "apiVersion": API_VERSION,
        "kind": "Harness",
        "metadata": app_doc["metadata"],
        "extends": list(app_doc.get("extends", [])),
        **merged.data,
    }
    spec = validate_spec(data, merged.provenance)
    compile_rules(spec)
    check_bands(merged.data, merged.provenance)
    check_sidecar_guards(merged.data, merged.locks)
    check_plugin_profiles(spec, merged.layers)
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
    catalog: PluginCatalog | None = None,
) -> EffectiveSpec:
    """Load ``harness.yaml`` with its profiles and environment overlay.

    Args:
        path: The app spec, usually ``harness.yaml``.
        env: Overlay to apply (``harness.<env>.yaml``); defaults to ``$HARNESSWEAVER_ENV``.
            A missing overlay file is not an error; ``spec explain`` lists the layers used.
        profile_dirs: Extra directories to search for ``org://`` profiles.
        resolvers: Replace the default profile resolvers entirely.
        catalog: Where plugin profiles (``profile://<namespace>.<name>``) are found;
            defaults to the installed plugins.

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
            PluginProfiles(catalog or PluginCatalog.default()),
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
    # Profiles only: the app spec's own file name says nothing about what was merged.
    old_layers = {layer.layer for layer in before.layers if layer.kind.is_profile}
    new_layers = {layer.layer for layer in after.layers if layer.kind.is_profile}
    return SpecDiff(
        changes=diff_data(before.data, after.data),
        locks_added=tuple(sorted(new_locks - old_locks)),
        locks_removed=tuple(sorted(old_locks - new_locks)),
        layers_added=tuple(sorted(new_layers - old_layers)),
        layers_removed=tuple(sorted(old_layers - new_layers)),
        level_before=before.level.level.value,
        level_after=after.level.level.value,
    )
