"""Durations written as compact strings: ``"250ms"``, ``"20s"``, ``"5m"``, ``"1h30m"``, ``"1d"``.

Specs use durations for deadlines, timeouts, TTLs and approval windows. The
format is part of the contract (fixtures suite ``durations``), so every
language parses and prints it the same way:

* A duration is one or more ``<number><unit>`` segments with units ``d``,
  ``h``, ``m``, ``s`` and ``ms``, largest unit first, each unit at most once.
* Numbers may have a fractional part, but the total must be a whole number of
  milliseconds.
* A bare number (not a string) means seconds.
* Durations are never negative.
"""

import math
import re
from datetime import timedelta
from decimal import Decimal, InvalidOperation
from typing import Annotated, Final

from pydantic import BeforeValidator, PlainSerializer, WithJsonSchema

__all__ = [
    "DURATION_PATTERN",
    "Duration",
    "duration_ms",
    "format_duration",
    "parse_duration",
]

_UNITS_MS: Final[dict[str, int]] = {
    "d": 86_400_000,
    "h": 3_600_000,
    "m": 60_000,
    "s": 1_000,
    "ms": 1,
}
_UNIT_ORDER: Final[tuple[str, ...]] = ("d", "h", "m", "s", "ms")
_SEGMENT: Final = re.compile(r"(\d+(?:\.\d+)?)(ms|d|h|m|s)")

DURATION_PATTERN: Final = r"^(\d+(\.\d+)?(ms|d|h|m|s))+$"
"""Regular expression for the string form, used in the JSON Schema."""


def _whole_ms(value: Decimal, source: object) -> int:
    if value != value.to_integral_value():
        raise ValueError(f"duration {source!r} is not a whole number of milliseconds")
    return int(value)


def _parse_string(text: str) -> int:
    if not text:
        raise ValueError("duration is empty")
    position = 0
    total = 0
    last_rank = -1
    while position < len(text):
        match = _SEGMENT.match(text, position)
        if match is None:
            raise ValueError(f"invalid duration {text!r}; expected e.g. '250ms', '20s', '1h30m'")
        number, unit = match.groups()
        rank = _UNIT_ORDER.index(unit)
        if rank <= last_rank:
            raise ValueError(f"invalid duration {text!r}; units must go from largest to smallest")
        last_rank = rank
        total += _whole_ms(Decimal(number) * _UNITS_MS[unit], text)
        position = match.end()
    return total


def parse_duration(value: object) -> timedelta:
    """Parse a duration from a string, a number of seconds, or a ``timedelta``.

    Raises:
        ValueError: If the value is not a valid, non-negative duration.
    """
    if isinstance(value, timedelta):
        if value < timedelta(0):
            raise ValueError("duration must not be negative")
        return value
    if isinstance(value, bool):
        raise ValueError("duration must be a string or a number of seconds, not a bool")
    if isinstance(value, int | float):
        if not math.isfinite(value) or value < 0:
            raise ValueError(f"duration {value!r} must be a finite, non-negative number of seconds")
        try:
            ms = _whole_ms(Decimal(str(value)) * 1000, value)
        except InvalidOperation as exc:  # pragma: no cover - finite floats always convert
            raise ValueError(f"invalid duration {value!r}") from exc
        return timedelta(milliseconds=ms)
    if isinstance(value, str):
        return timedelta(milliseconds=_parse_string(value.strip()))
    raise ValueError(
        f"duration must be a string or a number of seconds, not {type(value).__name__}"
    )


def duration_ms(value: timedelta) -> int:
    """Return a duration as whole milliseconds.

    Raises:
        ValueError: If the duration is negative or has sub-millisecond precision.
    """
    if value < timedelta(0):
        raise ValueError("duration must not be negative")
    ms, rest = divmod(value, timedelta(milliseconds=1))
    if rest:
        raise ValueError("duration has sub-millisecond precision")
    return ms


def format_duration(value: timedelta) -> str:
    """Format a duration in its canonical string form, e.g. ``"1h30m"``, ``"0s"``."""
    remaining = duration_ms(value)
    if remaining == 0:
        return "0s"
    parts: list[str] = []
    for unit in _UNIT_ORDER:
        count, remaining = divmod(remaining, _UNITS_MS[unit])
        if count:
            parts.append(f"{count}{unit}")
    return "".join(parts)


Duration = Annotated[
    timedelta,
    BeforeValidator(parse_duration),
    PlainSerializer(format_duration, return_type=str),
    WithJsonSchema(
        {
            "anyOf": [
                {"type": "string", "pattern": DURATION_PATTERN},
                {"type": "number", "minimum": 0},
            ],
            "description": "A duration such as '250ms', '20s', '5m' or '1h30m', "
            "or a number of seconds.",
        }
    ),
]
"""A ``timedelta`` that validates from the duration format and serializes to it."""
