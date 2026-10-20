"""How graders read values: JSON equality, dotted paths and an output's text.

These are part of the ``evals`` contract (fixtures suite ``evals``), so every
language reads outputs the same way.
"""

import json
from typing import Final

from pydantic import JsonValue

__all__ = ["MISSING", "json_equal", "output_text", "value_at"]


class _Missing:
    def __repr__(self) -> str:
        return "MISSING"


MISSING: Final = _Missing()
"""What :func:`value_at` returns for a path that leads nowhere."""


def _number(value: object) -> bool:
    return isinstance(value, int | float) and not isinstance(value, bool)


def json_equal(a: object, b: object) -> bool:
    """JSON equality: numbers by value (``1 == 1.0``), never a boolean as a number, maps
    whatever their key order."""
    if _number(a) and _number(b):
        return a == b
    if isinstance(a, list) and isinstance(b, list):
        return len(a) == len(b) and all(json_equal(x, y) for x, y in zip(a, b, strict=True))  # pyright: ignore[reportUnknownArgumentType, reportUnknownVariableType]
    if isinstance(a, dict) and isinstance(b, dict):
        return a.keys() == b.keys() and all(json_equal(a[k], b[k]) for k in a)  # pyright: ignore[reportUnknownVariableType, reportUnknownArgumentType]
    if type(a) is not type(b):
        return False
    return a == b


def value_at(value: JsonValue, path: str) -> JsonValue | _Missing:
    """Follow a dotted path (``line_items.1.amount``): map keys, and list indexes from 0."""
    current: JsonValue = value
    for part in path.split("."):
        if isinstance(current, dict) and part in current:
            current = current[part]
        elif isinstance(current, list) and part.isdigit() and int(part) < len(current):
            current = current[int(part)]
        else:
            return MISSING
    return current


def _canonical(value: JsonValue) -> JsonValue:
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, list):
        return [_canonical(v) for v in value]
    if isinstance(value, dict):
        return {k: _canonical(v) for k, v in value.items()}
    return value


def output_text(value: JsonValue) -> str:
    """The text graders search: a string as it is, nothing for null, and anything else
    as canonical JSON (sorted keys, no spaces, non-ASCII kept, integral numbers
    without a fraction)."""
    if isinstance(value, str):
        return value
    if value is None:
        return ""
    return json.dumps(_canonical(value), sort_keys=True, separators=(",", ":"), ensure_ascii=False)
