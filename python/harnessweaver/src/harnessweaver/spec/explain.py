"""``spec explain`` (where every value came from) and ``spec diff`` (what changed)."""

import json
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal

from harnessweaver.core.durations import format_duration
from harnessweaver.spec._raw import as_list, as_map
from harnessweaver.spec.merge import KEYED_LISTS, Bound, Lock, Provenance
from harnessweaver.spec.paths import Item, SpecPath, format_path, is_prefix, matches

__all__ = [
    "ExplainRow",
    "SpecChange",
    "SpecDiff",
    "diff_data",
    "explain_rows",
    "flatten",
    "origin_of",
    "render_diff",
    "render_explain",
]


def _keyed(path: SpecPath) -> bool:
    return any(matches(pattern, path) for pattern in KEYED_LISTS)


def flatten(data: Any, path: SpecPath = ()) -> Iterator[tuple[SpecPath, Any]]:
    """Yield every leaf value with its path. Keyed-list items are addressed by id."""
    mapping = as_map(data)
    if mapping:
        for key, value in mapping.items():
            child: SpecPath = (*path, str(key))
            items = as_list(value)
            if items and _keyed(child):
                for item in items:
                    entry = as_map(item) or {}
                    item_path: SpecPath = (*child, Item(str(entry.get("id"))))
                    for leaf_path, leaf in flatten(entry, item_path):
                        if leaf_path != (*item_path, "id"):
                            yield leaf_path, leaf
            else:
                yield from flatten(value, child)
    else:
        yield path, data


def origin_of(path: SpecPath, provenance: Mapping[str, Provenance]) -> Provenance | None:
    """The layer that set ``path``, or the nearest ancestor that was set as a whole."""
    for length in range(len(path), 0, -1):
        found = provenance.get(format_path(path[:length]))
        if found is not None:
            return found
    return None


def _show(value: Any) -> str:
    return json.dumps(value, ensure_ascii=True, separators=(", ", ": "))


@dataclass(frozen=True, slots=True)
class ExplainRow:
    path: str
    value: Any
    origin: Provenance | None
    locked_by: Lock | None
    bounds: tuple[Bound, ...]


def explain_rows(
    data: Mapping[str, Any],
    provenance: Mapping[str, Provenance],
    locks: Sequence[Lock],
    bounds: Sequence[Bound],
) -> list[ExplainRow]:
    """Every effective value with the layer it came from, its lock and its bounds."""
    rows: list[ExplainRow] = []
    for path, value in flatten(dict(data)):
        lock = next((lk for lk in locks if is_prefix(lk.path, path)), None)
        covering = tuple(b for b in bounds if matches(b.path, path))
        rows.append(
            ExplainRow(format_path(path), value, origin_of(path, provenance), lock, covering)
        )
    return rows


def _bound_text(bound: Bound) -> str:
    def show(limit: Any) -> str:
        return format_duration(limit) if not isinstance(limit, float) else f"{limit:g}"

    parts: list[str] = []
    if bound.minimum is not None:
        parts.append(f"min {show(bound.minimum)}")
    if bound.maximum is not None:
        parts.append(f"max {show(bound.maximum)}")
    return " ".join(parts)


def render_explain(rows: Sequence[ExplainRow]) -> str:
    """Plain-text table: ``path = value  <- layer  [locked] [max 5]``."""
    lines: list[str] = []
    width = max((len(row.path) for row in rows), default=0)
    for row in rows:
        origin = row.origin.describe() if row.origin else "(unset)"
        notes = ""
        if row.locked_by is not None:
            notes += f"  [locked by {row.locked_by.declared_by.layer}]"
        for bound in row.bounds:
            notes += f"  [{_bound_text(bound)}]"
        lines.append(f"{row.path.ljust(width)} = {_show(row.value)}  <- {origin}{notes}")
    return "\n".join(lines)


@dataclass(frozen=True, slots=True)
class SpecChange:
    path: str
    kind: Literal["added", "removed", "changed"]
    before: Any = None
    after: Any = None


@dataclass(frozen=True, slots=True)
class SpecDiff:
    changes: tuple[SpecChange, ...]
    locks_added: tuple[str, ...] = ()
    locks_removed: tuple[str, ...] = ()
    level_before: str | None = None
    level_after: str | None = None

    @property
    def empty(self) -> bool:
        return not (self.changes or self.locks_added or self.locks_removed) and (
            self.level_before == self.level_after
        )


def diff_data(before: Mapping[str, Any], after: Mapping[str, Any]) -> tuple[SpecChange, ...]:
    """Leaf-by-leaf differences between two merged specs."""
    old = {format_path(p): v for p, v in flatten(dict(before))}
    new = {format_path(p): v for p, v in flatten(dict(after))}
    changes: list[SpecChange] = []
    for path in sorted(old.keys() | new.keys()):
        if path not in new:
            changes.append(SpecChange(path, "removed", before=old[path]))
        elif path not in old:
            changes.append(SpecChange(path, "added", after=new[path]))
        elif _show(old[path]) != _show(new[path]):
            changes.append(SpecChange(path, "changed", old[path], new[path]))
    return tuple(changes)


def render_diff(diff: SpecDiff) -> str:
    """A Markdown summary, suitable for a pull request comment."""
    if diff.empty:
        return "No changes to the effective spec."
    lines = ["| Path | Change | Before | After |", "| --- | --- | --- | --- |"]
    for change in diff.changes:
        before = "" if change.kind == "added" else f"`{_show(change.before)}`"
        after = "" if change.kind == "removed" else f"`{_show(change.after)}`"
        lines.append(f"| `{change.path}` | {change.kind} | {before} | {after} |")
    extra: list[str] = []
    extra.extend(f"- Lock added: `{lock}`" for lock in diff.locks_added)
    extra.extend(f"- Lock removed: `{lock}`" for lock in diff.locks_removed)
    if diff.level_before != diff.level_after:
        extra.append(f"- Adoption level: {diff.level_before} -> {diff.level_after}")
    return "\n".join([*lines, "", *extra] if extra else lines)
