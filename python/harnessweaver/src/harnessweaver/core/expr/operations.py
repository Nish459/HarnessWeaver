"""Value operations for the evaluator: equality, comparison, arithmetic and
conversions. Errors name types, never values (R9).
"""

import math
import re
from decimal import Decimal
from typing import Final

from harnessweaver.core.expr.values import INT64_MAX, INT64_MIN, Key, Value, type_name

__all__ = [
    "EvalFailure",
    "arithmetic",
    "compare",
    "equals",
    "int64",
    "is_int",
    "lookup",
    "matches",
    "size",
    "to_double",
    "to_int",
    "to_string",
]


class EvalFailure(Exception):
    """An evaluation error at a position in the expression."""

    def __init__(self, message: str, pos: int) -> None:
        super().__init__(message)
        self.message = message
        self.pos = pos


_INT_TEXT: Final = re.compile(r"^[+-]?\d+$")
_DOUBLE_TEXT: Final = re.compile(r"^[+-]?(\d+(\.\d*)?|\.\d+)([eE][+-]?\d+)?$")


def is_number(value: Value) -> bool:
    return isinstance(value, int | float) and not isinstance(value, bool)


def is_int(value: Value) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def int64(value: int, pos: int) -> int:
    if not INT64_MIN <= value <= INT64_MAX:
        raise EvalFailure("integer overflow", pos)
    return value


def format_double(value: float) -> str:
    """Format a double the way JavaScript's ``Number#toString`` does.

    Both language implementations use this format, so ``string(1.5)`` gives the
    same text everywhere.
    """
    if math.isnan(value):
        return "NaN"
    if math.isinf(value):
        return "Infinity" if value > 0 else "-Infinity"
    if value == 0:
        return "0"
    sign = "-" if value < 0 else ""
    # repr gives the shortest digits that round-trip, as JavaScript does.
    parts = Decimal(repr(abs(value))).normalize().as_tuple()
    digits = "".join(str(d) for d in parts.digits)
    assert isinstance(parts.exponent, int)
    k = len(digits)
    n = parts.exponent + k  # value = 0.<digits> * 10**n
    if k <= n <= 21:
        text = digits + "0" * (n - k)
    elif 0 < n <= 21:
        text = f"{digits[:n]}.{digits[n:]}"
    elif -6 < n <= 0:
        text = "0." + "0" * -n + digits
    else:
        exponent = n - 1
        mantissa = digits[0] + ("." + digits[1:] if k > 1 else "")
        text = f"{mantissa}e{'+' if exponent > 0 else '-'}{abs(exponent)}"
    return sign + text


def equals(a: Value, b: Value) -> bool:
    if is_number(a) and is_number(b):
        return a == b
    if type_name(a) != type_name(b):
        return False
    if isinstance(a, list) and isinstance(b, list):
        return len(a) == len(b) and all(equals(x, y) for x, y in zip(a, b, strict=True))
    if isinstance(a, dict) and isinstance(b, dict):
        if len(a) != len(b):
            return False
        for key, value in a.items():
            found, other = lookup(b, key)
            if not found or not equals(value, other):
                return False
        return True
    return a == b


def lookup(mapping: dict[Key, Value], key: Value) -> tuple[bool, Value]:
    """Find ``key`` in a map, comparing keys like values (Python's ``True == 1`` doesn't apply)."""
    for candidate, value in mapping.items():
        if equals(candidate, key):
            return True, value
    return False, None


def compare(a: Value, b: Value, pos: int) -> int:
    if is_number(a) and is_number(b):
        assert isinstance(a, int | float)
        assert isinstance(b, int | float)
        return (a > b) - (a < b)
    if isinstance(a, str) and isinstance(b, str):
        return (a > b) - (a < b)
    if isinstance(a, bool) and isinstance(b, bool):
        return int(a) - int(b)
    raise EvalFailure(f"can't compare {type_name(a)} with {type_name(b)}", pos)


def arithmetic(op: str, a: Value, b: Value, pos: int) -> Value:
    if op == "+":
        if isinstance(a, str) and isinstance(b, str):
            return a + b
        if isinstance(a, list) and isinstance(b, list):
            return [*a, *b]
    if not (is_number(a) and is_number(b)):
        raise EvalFailure(f"no operator {op!r} for {type_name(a)} and {type_name(b)}", pos)
    assert isinstance(a, int | float)
    assert isinstance(b, int | float)
    if is_int(a) and is_int(b):
        assert isinstance(a, int)
        assert isinstance(b, int)
        if op == "+":
            return int64(a + b, pos)
        if op == "-":
            return int64(a - b, pos)
        if op == "*":
            return int64(a * b, pos)
        if b == 0:
            raise EvalFailure("division by zero" if op == "/" else "modulus by zero", pos)
        quotient = abs(a) // abs(b)
        if op == "/":
            return int64(quotient if (a < 0) == (b < 0) else -quotient, pos)
        remainder = abs(a) - quotient * abs(b)
        return remainder if a >= 0 else -remainder
    if op == "%":
        raise EvalFailure("'%' needs two ints", pos)
    x, y = float(a), float(b)
    if op == "+":
        return x + y
    if op == "-":
        return x - y
    if op == "*":
        return x * y
    if y == 0:  # IEEE 754 division, as in CEL and JavaScript
        if x == 0 or math.isnan(x):
            return math.nan
        return math.copysign(math.inf, x) * math.copysign(1.0, y)
    return x / y


def to_int(value: Value, pos: int) -> int:
    if isinstance(value, bool):
        raise EvalFailure("int() doesn't accept bool", pos)
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise EvalFailure("int() needs a finite double", pos)
        return int64(math.trunc(value), pos)
    if isinstance(value, str) and _INT_TEXT.match(value):
        return int64(int(value), pos)
    raise EvalFailure(f"int() can't convert {type_name(value)}", pos)


def to_double(value: Value, pos: int) -> float:
    if isinstance(value, bool):
        raise EvalFailure("double() doesn't accept bool", pos)
    if isinstance(value, int | float):
        return float(value)
    if isinstance(value, str) and _DOUBLE_TEXT.match(value):
        return float(value)
    raise EvalFailure(f"double() can't convert {type_name(value)}", pos)


def to_string(value: Value, pos: int) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return format_double(value)
    raise EvalFailure(f"string() can't convert {type_name(value)}", pos)


def matches(text: Value, pattern: Value, pos: int) -> bool:
    if not (isinstance(text, str) and isinstance(pattern, str)):
        raise EvalFailure("matches() needs a string and a pattern", pos)
    try:
        return re.search(pattern, text) is not None
    except re.error as exc:
        raise EvalFailure(f"invalid regular expression: {exc.msg}", pos) from None


def size(value: Value, pos: int) -> int:
    if isinstance(value, str | list | dict):
        return len(value)
    raise EvalFailure(f"size() doesn't accept {type_name(value)}", pos)
