"""cel-lite values and how host data becomes them."""

import math
from collections.abc import Mapping, Sequence
from enum import Enum
from typing import Final, cast

from pydantic import BaseModel

__all__ = ["INT64_MAX", "INT64_MIN", "Key", "Value", "from_host", "type_name"]

type Key = bool | int | str
type Value = bool | int | float | str | list[Value] | dict[Key, Value] | None

INT64_MIN: Final = -(2**63)
INT64_MAX: Final = 2**63 - 1


class ConversionError(ValueError):
    """Host data that cel-lite can't represent."""


def type_name(value: object) -> str:
    """The cel-lite type name of a value, for error messages (never the value itself, R9)."""
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, int):
        return "int"
    if isinstance(value, float):
        return "double"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        return "list"
    if isinstance(value, dict):
        return "map"
    return type(value).__name__


def from_host(obj: object) -> Value:
    """Convert variables into cel-lite values.

    Pydantic models are dumped in JSON mode. Integral floats from data become
    ints, so data behaves the same here as in TypeScript, where JSON numbers
    have no int/double distinction (fixtures suite ``expr``).

    Raises:
        ConversionError: For types cel-lite doesn't support.
    """
    if isinstance(obj, BaseModel):
        return from_host(obj.model_dump(mode="json"))
    if isinstance(obj, Enum):
        return from_host(obj.value)
    if obj is None or isinstance(obj, bool | str):
        return obj
    if isinstance(obj, int):
        if not INT64_MIN <= obj <= INT64_MAX:
            raise ConversionError("integer is outside the 64-bit range")
        return obj
    if isinstance(obj, float):
        if math.isfinite(obj) and obj.is_integer() and INT64_MIN <= obj <= INT64_MAX:
            return int(obj)
        return obj
    if isinstance(obj, Mapping):
        result: dict[Key, Value] = {}
        for key, item in cast(Mapping[object, object], obj).items():
            if not isinstance(key, bool | int | str):
                raise ConversionError(
                    f"map keys must be strings, ints or bools, not {type_name(key)}"
                )
            result[key] = from_host(item)
        return result
    if isinstance(obj, Sequence) and not isinstance(obj, bytes | bytearray):
        return [from_host(item) for item in cast(Sequence[object], obj)]
    raise ConversionError(f"unsupported value of type {type(obj).__name__}")
