"""Merging layers in order: keyed lists, locks and generated ids (R1)."""

import copy
import itertools
from collections.abc import Iterator, Mapping, Sequence
from typing import Any, Final

from harnessweaver.core.errors import LockViolation, SpecError
from harnessweaver.spec._raw import as_list, as_map
from harnessweaver.spec.merge.bounds import check_bounds, check_removed_limits, read_bounds
from harnessweaver.spec.merge.layers import (
    KEYED_LISTS,
    Bound,
    Layer,
    Lock,
    Merged,
    Provenance,
    RawMap,
    item_id,
)
from harnessweaver.spec.paths import Item, SpecPath, format_path, is_prefix, matches, parse_path

__all__ = ["merge_layers"]

_PROFILE_ONLY: Final = frozenset({"locks", "bounds", "require_level"})
_AUTO_PREFIX: Final = "~auto"
_FORBIDDEN_KEY: Final = "__proto__"  # would set a prototype in TypeScript, not a key (R11)


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
            if is_prefix(lock.path[: len(path)], path):
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
            if key == _FORBIDDEN_KEY:
                where = format_path((*path, key))
                raise SpecError(f"{where}: {key} can't be a key (in {prov.describe()})", path=where)
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
            elif item_id.startswith(_AUTO_PREFIX):
                # Only the merger makes these: a layer naming one could reach an id-less item
                # that a lock can only name by its final id (R1).
                raise SpecError(f"ids in {where} can't start with {_AUTO_PREFIX}", path=where)
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
                yield from _iter_keyed_lists(item, (*child, Item(item_id(item))))
        else:
            yield from _iter_keyed_lists(value, child)


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
        new_bounds = read_bounds(body.pop("bounds", {}), prov)
        merger.data = merger.merge_map((), merger.data, body, prov)
        merger.locks.extend(new_locks)  # a layer's own locks bind only later layers
        bounds.extend(new_bounds)
        applied.append(prov)
    merger.assign_auto_ids()
    merged = Merged(merger.data, merger.provenance, merger.locks, bounds, applied)
    check_bounds(merged.data, bounds, merged.provenance)
    check_removed_limits(merged.data, bounds, merged.provenance)
    return merged
