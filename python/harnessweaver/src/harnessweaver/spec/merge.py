"""Layered merging of spec documents, with provenance, locks and bounds (DESIGNS No. 11).

The rules, which the ``merge`` fixtures pin down for every language:

* Layers merge in order: defaults, built-in profiles, org profiles, the app
  spec, then an environment overlay.
* Scalars and plain lists: the later layer wins. Maps merge key by key.
* Keyed lists (guardrail stages, middleware, routing cascades, rule lists)
  merge by ``id``: an item with a known id updates that item in place, new
  items are appended, and earlier items keep their position. Items without an
  id are appended and get an id ``<use>#<n>`` after merging (``rule#<n>`` in
  rule lists, ``item#<n>`` for other items without a ``use``), skipping ids
  already taken.
* ``null`` can unset a scalar, but can't remove a map or a keyed list.
* A lock declared by a profile covers that path and everything under it for
  all later layers. Changing a locked value is a ``LockViolation`` (R1);
  restating the same value is allowed.
* Bounds declared by profiles accumulate and are checked on the merged
  result. A value out of bounds is a ``BoundViolation``, never clamped (R10).
  Bounds on ``budgets.per_run.<field>`` also apply to every task's budget.
"""

import copy
import itertools
import math
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import timedelta
from enum import StrEnum
from typing import Any, Final

from harnessweaver.core.durations import format_duration, parse_duration
from harnessweaver.core.errors import BoundViolation, LockViolation, SpecError
from harnessweaver.spec._raw import as_list, as_map
from harnessweaver.spec.paths import Item, SpecPath, format_path, is_prefix, matches, parse_path

__all__ = [
    "KEYED_LISTS",
    "Bound",
    "Layer",
    "LayerKind",
    "Lock",
    "Merged",
    "Provenance",
    "check_bounds",
    "merge_layers",
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

_PROFILE_ONLY: Final = frozenset({"locks", "bounds", "require_level"})
_AUTO_PREFIX: Final = "~auto"

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


def _is_keyed(path: SpecPath) -> bool:
    return any(matches(pattern, path) for pattern in KEYED_LISTS)


def _same(a: Any, b: Any) -> bool:
    """Equality that keeps bools apart from numbers, as YAML and JSON do."""
    if isinstance(a, bool) or isinstance(b, bool):
        return type(a) is type(b) and a == b
    map_a, map_b = as_map(a), as_map(b)
    if map_a is not None and map_b is not None:
        return map_a.keys() == map_b.keys() and all(_same(map_a[k], map_b[k]) for k in map_a)
    list_a, list_b = as_list(a), as_list(b)
    if list_a is not None and list_b is not None:
        return len(list_a) == len(list_b) and all(
            _same(x, y) for x, y in zip(list_a, list_b, strict=True)
        )
    return bool(a == b)


def _normalize(body: RawMap) -> RawMap:
    """Expand shorthands so layers merge field by field."""
    for task in (as_map(body.get("tasks")) or {}).values():
        task_map = as_map(task)
        if task_map is not None and isinstance(task_map.get("runner"), str):
            task_map["runner"] = {"use": task_map["runner"]}
    tools = as_map(body.get("tools"))
    if tools is not None and isinstance(tools.get("manifests"), str):
        tools["manifests"] = [tools["manifests"]]
    return body


def _item_id(item: object) -> str:
    entry = as_map(item)
    return str(entry.get("id")) if entry is not None else ""


class _Merger:
    def __init__(self) -> None:
        self.data: RawMap = {}
        self.provenance: dict[str, Provenance] = {}
        self.locks: list[Lock] = []
        self.auto = itertools.count(1)

    # -- locks -----------------------------------------------------------------------------

    def check_locks(self, path: SpecPath) -> None:
        for lock in self.locks:
            if is_prefix(lock.path, path):
                raise LockViolation(
                    f"{format_path(path)} is locked by {lock.declared_by.describe()} "
                    f"(lock {lock.text!r}); it can't be changed (R1)",
                    path=format_path(path),
                    lock=lock.text,
                )

    def check_subtree_locks(self, path: SpecPath) -> None:
        """A replaced subtree must not contain locked values either."""
        self.check_locks(path)
        for lock in self.locks:
            if is_prefix(path, lock.path):
                raise LockViolation(
                    f"replacing {format_path(path)} would change {lock.text}, which "
                    f"{lock.declared_by.describe()} locked (R1)",
                    path=format_path(path),
                    lock=lock.text,
                )

    # -- merging ---------------------------------------------------------------------------

    def merge_value(self, path: SpecPath, current: Any, incoming: Any, prov: Provenance) -> Any:
        where = format_path(path)
        if incoming is None:
            if as_map(current) is not None or (as_list(current) is not None and _is_keyed(path)):
                raise SpecError(
                    f"{where} can't be removed by setting it to null (in {prov.describe()})",
                    path=where,
                )
            return self.set_leaf(path, current, None, prov)
        incoming_map, incoming_list = as_map(incoming), as_list(incoming)
        if current is None and (incoming_map is not None or incoming_list is not None):
            self.check_locks(path)  # creating even an empty section is a change
        if as_list(current) is not None and _is_keyed(path) and incoming_list is None:
            raise SpecError(f"{where} must stay a list (in {prov.describe()})", path=where)
        if incoming_map is not None:
            current_map = as_map(current)
            if current is None or current_map is not None:
                return self.merge_map(path, current_map, incoming_map, prov)
            return self.replace(path, current, incoming, prov)
        if incoming_list is not None and _is_keyed(path):
            current_list = as_list(current)
            if current is None or current_list is not None:
                return self.merge_keyed(path, current_list or [], incoming_list, prov)
            return self.replace(path, current, incoming, prov)
        if as_map(current) is not None:
            return self.replace(path, current, incoming, prov)
        return self.set_leaf(path, current, incoming, prov)

    def set_leaf(self, path: SpecPath, current: Any, incoming: Any, prov: Provenance) -> Any:
        key = format_path(path)
        changed = not _same(current, incoming)
        if changed:
            self.check_locks(path)
        if changed or key not in self.provenance:
            self.provenance[key] = prov
        return copy.deepcopy(incoming)

    def replace(self, path: SpecPath, current: Any, incoming: Any, prov: Provenance) -> Any:
        if _same(current, incoming):
            return current
        self.check_subtree_locks(path)
        prefix = format_path(path)
        stale = [
            k for k in self.provenance if k == prefix or k.startswith((f"{prefix}.", f"{prefix}["))
        ]
        for key in stale:
            del self.provenance[key]
        self.provenance[prefix] = prov
        return copy.deepcopy(incoming)

    def merge_map(
        self,
        path: SpecPath,
        current: Mapping[Any, Any] | None,
        incoming: Mapping[Any, Any],
        prov: Provenance,
    ) -> RawMap:
        result: RawMap = dict(current) if current is not None else {}
        for key, value in incoming.items():
            if not isinstance(key, str):
                where = format_path(path) or "spec"
                raise SpecError(f"{where} has a non-string key", path=format_path(path))
            result[key] = self.merge_value((*path, key), result.get(key), value, prov)
        return result

    def merge_keyed(
        self, path: SpecPath, current: list[Any], incoming: list[Any], prov: Provenance
    ) -> list[Any]:
        where = format_path(path)
        result: list[Any] = list(current)
        positions: dict[str, int] = {}
        for index, existing in enumerate(result):
            entry = as_map(existing)
            if entry is not None and isinstance(entry.get("id"), str):
                positions[entry["id"]] = index
        for raw in incoming:
            item = as_map(raw)
            if item is None:
                raise SpecError(f"items of {where} must be maps", path=where)
            item_id = item.get("id")
            if item_id is None:
                item_id = f"{_AUTO_PREFIX}{next(self.auto)}~"
                item = {**item, "id": item_id}
            elif not isinstance(item_id, str) or not item_id:
                raise SpecError(f"ids in {where} must be non-empty strings", path=where)
            item_path = (*path, Item(item_id))
            if item_id in positions:
                position = positions[item_id]
                result[position] = self.merge_map(item_path, as_map(result[position]), item, prov)
            else:
                positions[item_id] = len(result)
                result.append(self.merge_map(item_path, None, item, prov))
        return result

    # -- finishing -------------------------------------------------------------------------

    def assign_auto_ids(self) -> None:
        renames: dict[str, str] = {}
        for path, items in _iter_keyed_lists(self.data):
            entries = [entry for entry in map(as_map, items) if entry is not None]
            taken = {str(entry.get("id")) for entry in entries}
            counters: dict[str, int] = {}
            for entry in entries:
                current_id = str(entry.get("id", ""))
                if not current_id.startswith(_AUTO_PREFIX):
                    continue
                fallback = "rule" if path[-1] == "rules" else "item"
                use = str(entry.get("use", fallback))
                while True:
                    counters[use] = counters.get(use, 0) + 1
                    candidate = f"{use}#{counters[use]}"
                    if candidate not in taken:
                        break
                taken.add(candidate)
                renames[format_path((*path, Item(current_id)))] = format_path(
                    (*path, Item(candidate))
                )
                entry["id"] = candidate
        if renames:
            updated: dict[str, Provenance] = {}
            for key, prov in self.provenance.items():
                for old, new in renames.items():
                    if key == old or key.startswith((f"{old}.", f"{old}[")):
                        key = new + key[len(old) :]
                        break
                updated[key] = prov
            self.provenance = updated


def _iter_keyed_lists(data: Any, path: SpecPath = ()) -> Iterator[tuple[SpecPath, list[Any]]]:
    for key, value in (as_map(data) or {}).items():
        child: SpecPath = (*path, str(key))
        items = as_list(value)
        if items is not None and _is_keyed(child):
            yield child, items
            for item in items:
                yield from _iter_keyed_lists(item, (*child, Item(_item_id(item))))
        else:
            yield from _iter_keyed_lists(value, child)


def _parse_limit(value: Any, path: str, prov: Provenance) -> float | timedelta | None:
    if value is None:
        return None
    if isinstance(value, bool):
        raise SpecError(f"bound on {path} in {prov.describe()} must be a number or a duration")
    if isinstance(value, int | float):
        if not math.isfinite(value):
            raise SpecError(f"bound on {path} in {prov.describe()} must be finite")
        return float(value)
    if isinstance(value, str):
        try:
            return parse_duration(value)
        except ValueError as exc:
            raise SpecError(f"bound on {path} in {prov.describe()}: {exc}") from None
    raise SpecError(f"bound on {path} in {prov.describe()} must be a number or a duration")


def _read_bounds(raw: Any, prov: Provenance) -> list[Bound]:
    declared = as_map(raw)
    if declared is None:
        raise SpecError(f"bounds in {prov.describe()} must be a map of path to {{min, max}}")
    bounds: list[Bound] = []
    for key, spec in declared.items():
        text = str(key)
        where = f"bound on {text} in {prov.describe()}"
        limits = as_map(spec)
        if not limits or not set(limits) <= {"min", "max"}:
            raise SpecError(f"{where} must have min and/or max")
        try:
            path = parse_path(text)
        except ValueError as exc:
            raise SpecError(f"{exc} (in {prov.describe()})") from None
        minimum = _parse_limit(limits.get("min"), text, prov)
        maximum = _parse_limit(limits.get("max"), text, prov)
        if minimum is not None and maximum is not None:
            if isinstance(minimum, timedelta) != isinstance(maximum, timedelta):
                raise SpecError(f"{where} mixes a number and a duration")
            if _greater(minimum, maximum):
                raise SpecError(f"{where} has min above max")
        bounds.append(Bound(path, minimum, maximum, prov))
    return bounds


def _read_locks(raw: Any, prov: Provenance) -> list[Lock]:
    declared = as_list(raw)
    if declared is None or not all(isinstance(text, str) for text in declared):
        raise SpecError(f"locks in {prov.describe()} must be a list of paths")
    locks: list[Lock] = []
    for text in declared:
        try:
            locks.append(Lock(parse_path(str(text)), prov))
        except ValueError as exc:
            raise SpecError(f"{exc} (in {prov.describe()})") from None
    return locks


def merge_layers(layers: Sequence[Layer]) -> Merged:
    """Merge spec layers in order and check bounds.

    Layer bodies must already be stripped of ``apiVersion``, ``kind``,
    ``metadata`` and ``extends``.

    Raises:
        LockViolation: A layer changed a locked value.
        BoundViolation: A merged value is outside a bound.
        SpecError: A layer is malformed (for example, an app declaring locks).
    """
    merger = _Merger()
    bounds: list[Bound] = []
    applied: list[Provenance] = []
    for layer in layers:
        prov = layer.provenance
        body = _normalize(copy.deepcopy(dict(layer.data)))
        if not layer.kind.is_profile:
            declared = sorted(_PROFILE_ONLY & body.keys())
            if declared:
                raise SpecError(
                    f"{prov.describe()} declares {', '.join(declared)}, which only profiles may",
                    layer=layer.name,
                )
        new_locks = _read_locks(body.pop("locks", []), prov)
        new_bounds = _read_bounds(body.pop("bounds", {}), prov)
        merger.data = merger.merge_map((), merger.data, body, prov)
        merger.locks.extend(new_locks)  # a layer's own locks bind only later layers
        bounds.extend(new_bounds)
        applied.append(prov)
    merger.assign_auto_ids()
    merged = Merged(merger.data, merger.provenance, merger.locks, bounds, applied)
    check_bounds(merged.data, bounds, merged.provenance)
    return merged


def _iter_values(
    data: Any, pattern: SpecPath, path: SpecPath = ()
) -> Iterator[tuple[SpecPath, Any]]:
    if len(path) == len(pattern):
        yield path, data
        return
    want = pattern[len(path)]
    if isinstance(want, Item):
        for item in as_list(data) or []:
            entry = as_map(item)
            if entry is not None and (want.id == "*" or entry.get("id") == want.id):
                yield from _iter_values(entry, pattern, (*path, Item(_item_id(entry))))
        return
    mapping = as_map(data) or {}
    keys = list(mapping) if want == "*" else [want] if want in mapping else []
    for key in keys:
        yield from _iter_values(mapping[key], pattern, (*path, str(key)))


def _patterns_for(bound: Bound) -> list[SpecPath]:
    patterns = [bound.path]
    # Task budgets may not exceed what the org allows per run (DESIGNS No. 11).
    if len(bound.path) == 3 and bound.path[:2] == ("budgets", "per_run"):
        patterns.append(("tasks", "*", "budget", bound.path[2]))
    return patterns


def _greater(a: float | timedelta, b: float | timedelta) -> bool:
    if isinstance(a, timedelta) and isinstance(b, timedelta):
        return a > b
    if not isinstance(a, timedelta) and not isinstance(b, timedelta):
        return a > b
    raise TypeError("can't compare a number with a duration")


def _measure(value: Any, like: float | timedelta) -> float | timedelta:
    if isinstance(like, timedelta):
        return parse_duration(value)
    if isinstance(value, int | float) and not isinstance(value, bool):
        return float(value)
    raise TypeError("not a number")


def _show(limit: float | timedelta) -> str:
    return format_duration(limit) if isinstance(limit, timedelta) else f"{limit:g}"


def check_bounds(
    data: RawMap, bounds: Sequence[Bound], provenance: Mapping[str, Provenance]
) -> None:
    """Check every merged value against every bound that covers it (R10).

    Raises:
        BoundViolation: On the first value outside a bound.
    """
    for bound in bounds:
        like = bound.maximum if bound.maximum is not None else bound.minimum
        if like is None:
            continue
        for pattern in _patterns_for(bound):
            for path, value in _iter_values(data, pattern):
                if value is None:
                    continue
                key = format_path(path)
                origin = provenance.get(key)
                where = f" (set by {origin.describe()})" if origin else ""
                try:
                    measured = _measure(value, like)
                except (TypeError, ValueError):
                    raise SpecError(
                        f"{key}{where} can't be compared with the bound {bound.text}", path=key
                    ) from None
                shown = _show(measured) if isinstance(measured, timedelta) else repr(value)
                if bound.maximum is not None and _greater(measured, bound.maximum):
                    raise BoundViolation(
                        f"{key} = {shown}{where} is above the maximum {_show(bound.maximum)} "
                        f"that {bound.declared_by.describe()} allows (R10)",
                        path=key,
                        bound=bound.text,
                    )
                if bound.minimum is not None and _greater(bound.minimum, measured):
                    raise BoundViolation(
                        f"{key} = {shown}{where} is below the minimum {_show(bound.minimum)} "
                        f"that {bound.declared_by.describe()} allows (R10)",
                        path=key,
                        bound=bound.text,
                    )
