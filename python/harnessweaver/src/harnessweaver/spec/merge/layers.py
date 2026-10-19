"""What merging works on: layers, their provenance, locks, bounds and the result."""

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import timedelta
from enum import StrEnum
from typing import Any, Final

from harnessweaver.spec._raw import as_map
from harnessweaver.spec.paths import SpecPath, format_path, parse_path

__all__ = [
    "KEYED_LISTS",
    "Bound",
    "Layer",
    "LayerKind",
    "Lock",
    "Merged",
    "Provenance",
    "RawMap",
    "item_id",
]

KEYED_LISTS: Final[tuple[SpecPath, ...]] = tuple(
    parse_path(p)
    for p in (
        "guardrails.*",
        "middleware",
        "routing.*.cascade",
        "policy.rules",
        "validation.rules",
        "tasks.*.guardrails.*",
    )
)
"""Lists that merge by item ``id`` instead of being replaced."""


type RawMap = dict[str, Any]


class LayerKind(StrEnum):
    """Where a layer comes from. Only profile kinds may declare locks and bounds."""

    DEFAULTS = "defaults"
    PROFILE = "profile"
    ORG = "org"
    APP = "app"
    OVERLAY = "overlay"

    @property
    def is_profile(self) -> bool:
        return self in {LayerKind.DEFAULTS, LayerKind.PROFILE, LayerKind.ORG}


@dataclass(frozen=True, slots=True)
class Provenance:
    """The layer a value came from."""

    layer: str
    kind: LayerKind
    source: str | None = None

    def describe(self) -> str:
        return self.layer if self.source is None else f"{self.layer} ({self.source})"


@dataclass(frozen=True, slots=True)
class Layer:
    """One spec document to merge. ``data`` is the document body as parsed."""

    name: str
    kind: LayerKind
    data: Mapping[str, Any]
    source: str | None = None

    @property
    def provenance(self) -> Provenance:
        return Provenance(self.name, self.kind, self.source)


@dataclass(frozen=True, slots=True)
class Lock:
    path: SpecPath
    declared_by: Provenance

    @property
    def text(self) -> str:
        return format_path(self.path)


@dataclass(frozen=True, slots=True)
class Bound:
    """``min``/``max`` for a path pattern. Values are numbers or durations."""

    path: SpecPath
    minimum: float | timedelta | None
    maximum: float | timedelta | None
    declared_by: Provenance

    @property
    def text(self) -> str:
        return format_path(self.path)


@dataclass(slots=True)
class Merged:
    """The result of merging layers."""

    data: RawMap
    provenance: dict[str, Provenance] = field(default_factory=dict[str, Provenance])
    locks: list[Lock] = field(default_factory=list[Lock])
    bounds: list[Bound] = field(default_factory=list[Bound])
    layers: list[Provenance] = field(default_factory=list[Provenance])


def item_id(item: object) -> str:
    """The ``id`` of a keyed-list item, or an empty string."""
    entry = as_map(item)
    return str(entry.get("id")) if entry is not None else ""
