"""Reading bounds and checking the merged result against them (R10)."""

import math
from collections.abc import Iterator, Mapping, Sequence
from datetime import timedelta
from typing import Any

from harnessweaver.core.durations import format_duration, parse_duration
from harnessweaver.core.errors import BoundViolation, SpecError
from harnessweaver.spec._raw import as_list, as_map
from harnessweaver.spec.merge.layers import Bound, LayerKind, Provenance, RawMap, item_id
from harnessweaver.spec.paths import Item, SpecPath, format_path, parse_path

__all__ = ["check_bounds", "check_removed_limits", "read_bounds"]


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


def read_bounds(raw: Any, prov: Provenance) -> list[Bound]:
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
                yield from _iter_values(entry, pattern, (*path, Item(item_id(entry))))
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
    if isinstance(value, int | float) and not isinstance(value, bool) and math.isfinite(value):
        return float(value)
    raise TypeError("not a finite number")


def _show(limit: float | timedelta) -> str:
    return format_duration(limit) if isinstance(limit, timedelta) else f"{limit:g}"


def check_removed_limits(
    data: RawMap, bounds: Sequence[Bound], provenance: Mapping[str, Provenance]
) -> None:
    """Refuse a layer's ``null`` at a path with a maximum: it removes the limit (R10).

    This checks merged layers only. :func:`check_bounds` also sees a run's budget, where an
    unset field is normal. A null the framework defaults left in place removes nothing, and
    a null on a task budget leaves the per-run limit in force, so neither is refused.

    Raises:
        BoundViolation: On the first such value.
    """
    for bound in bounds:
        if bound.maximum is None:
            continue
        for path, value in _iter_values(data, bound.path):
            key = format_path(path)
            origin = provenance.get(key)
            if value is None and origin is not None and origin.kind is not LayerKind.DEFAULTS:
                raise BoundViolation(
                    f"{key} = null (set by {origin.describe()}) removes the maximum "
                    f"{_show(bound.maximum)} that {bound.declared_by.describe()} allows (R10)",
                    path=key,
                    bound=bound.text,
                )


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
