"""Checking each document's shape and validating the merged result."""

from collections.abc import Mapping, Sequence
from typing import Any, Final

from pydantic import JsonValue, ValidationError

from harnessweaver.core.errors import (
    SpecError,
)
from harnessweaver.spec._raw import as_list, as_map
from harnessweaver.spec.explain import origin_of
from harnessweaver.spec.merge import (
    Provenance,
)
from harnessweaver.spec.models import API_VERSION, HarnessSpec, ProfileSpec
from harnessweaver.spec.paths import Item, Segment, SpecPath, format_path

__all__ = ["check_document", "layer_body", "validate_spec"]

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


def check_document(document: Any, kind: str, where: str) -> dict[str, Any]:
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


def layer_body(document: Mapping[str, Any]) -> dict[str, Any]:
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


def validate_spec(data: dict[str, Any], provenance: Mapping[str, Provenance]) -> HarnessSpec:
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
