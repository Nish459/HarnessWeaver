"""Evaluator for cel-lite syntax trees.

Semantics follow CEL where cel-lite overlaps it:

* ``&&`` and ``||`` absorb errors: ``error || true`` is ``true``.
* Ints are 64-bit and overflow is an error; int division truncates toward zero.
* Mixing ints and doubles in arithmetic gives a double (CEL would refuse; this
  is a documented relaxation, see DESIGNS ADR-0004).
* Values of different types are never equal; comparing them is an error.
* Errors name types and keys, never values (R9).
"""

import math
import re
from collections.abc import Mapping
from decimal import Decimal
from typing import Final

from harnessweaver.core.expr.nodes import (
    Binary,
    Call,
    Comprehension,
    Conditional,
    Const,
    Ident,
    Index,
    ListExpr,
    MapExpr,
    Node,
    Presence,
    Select,
    Unary,
)
from harnessweaver.core.expr.values import INT64_MAX, INT64_MIN, Key, Value, type_name

__all__ = ["EvalFailure", "evaluate", "format_double"]


class EvalFailure(Exception):
    """An evaluation error at a position in the expression."""

    def __init__(self, message: str, pos: int) -> None:
        super().__init__(message)
        self.message = message
        self.pos = pos


_INT_TEXT: Final = re.compile(r"^[+-]?\d+$")
_DOUBLE_TEXT: Final = re.compile(r"^[+-]?(\d+(\.\d*)?|\.\d+)([eE][+-]?\d+)?$")


def _is_number(value: Value) -> bool:
    return isinstance(value, int | float) and not isinstance(value, bool)


def _is_int(value: Value) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _int64(value: int, pos: int) -> int:
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


def _equals(a: Value, b: Value) -> bool:
    if _is_number(a) and _is_number(b):
        return a == b
    if type_name(a) != type_name(b):
        return False
    if isinstance(a, list) and isinstance(b, list):
        return len(a) == len(b) and all(_equals(x, y) for x, y in zip(a, b, strict=True))
    if isinstance(a, dict) and isinstance(b, dict):
        if len(a) != len(b):
            return False
        for key, value in a.items():
            found, other = _lookup(b, key)
            if not found or not _equals(value, other):
                return False
        return True
    return a == b


def _lookup(mapping: dict[Key, Value], key: Value) -> tuple[bool, Value]:
    """Find ``key`` in a map, comparing keys like values (Python's ``True == 1`` doesn't apply)."""
    for candidate, value in mapping.items():
        if _equals(candidate, key):
            return True, value
    return False, None


def _compare(a: Value, b: Value, pos: int) -> int:
    if _is_number(a) and _is_number(b):
        assert isinstance(a, int | float)
        assert isinstance(b, int | float)
        return (a > b) - (a < b)
    if isinstance(a, str) and isinstance(b, str):
        return (a > b) - (a < b)
    if isinstance(a, bool) and isinstance(b, bool):
        return int(a) - int(b)
    raise EvalFailure(f"can't compare {type_name(a)} with {type_name(b)}", pos)


def _arithmetic(op: str, a: Value, b: Value, pos: int) -> Value:
    if op == "+":
        if isinstance(a, str) and isinstance(b, str):
            return a + b
        if isinstance(a, list) and isinstance(b, list):
            return [*a, *b]
    if not (_is_number(a) and _is_number(b)):
        raise EvalFailure(f"no operator {op!r} for {type_name(a)} and {type_name(b)}", pos)
    assert isinstance(a, int | float)
    assert isinstance(b, int | float)
    if _is_int(a) and _is_int(b):
        assert isinstance(a, int)
        assert isinstance(b, int)
        if op == "+":
            return _int64(a + b, pos)
        if op == "-":
            return _int64(a - b, pos)
        if op == "*":
            return _int64(a * b, pos)
        if b == 0:
            raise EvalFailure("division by zero" if op == "/" else "modulus by zero", pos)
        quotient = abs(a) // abs(b)
        if op == "/":
            return _int64(quotient if (a < 0) == (b < 0) else -quotient, pos)
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


def _to_int(value: Value, pos: int) -> int:
    if isinstance(value, bool):
        raise EvalFailure("int() doesn't accept bool", pos)
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise EvalFailure("int() needs a finite double", pos)
        return _int64(math.trunc(value), pos)
    if isinstance(value, str) and _INT_TEXT.match(value):
        return _int64(int(value), pos)
    raise EvalFailure(f"int() can't convert {type_name(value)}", pos)


def _to_double(value: Value, pos: int) -> float:
    if isinstance(value, bool):
        raise EvalFailure("double() doesn't accept bool", pos)
    if isinstance(value, int | float):
        return float(value)
    if isinstance(value, str) and _DOUBLE_TEXT.match(value):
        return float(value)
    raise EvalFailure(f"double() can't convert {type_name(value)}", pos)


def _to_string(value: Value, pos: int) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return format_double(value)
    raise EvalFailure(f"string() can't convert {type_name(value)}", pos)


def _matches(text: Value, pattern: Value, pos: int) -> bool:
    if not (isinstance(text, str) and isinstance(pattern, str)):
        raise EvalFailure("matches() needs a string and a pattern", pos)
    try:
        return re.search(pattern, text) is not None
    except re.error as exc:
        raise EvalFailure(f"invalid regular expression: {exc.msg}", pos) from None


def _size(value: Value, pos: int) -> int:
    if isinstance(value, str | list | dict):
        return len(value)
    raise EvalFailure(f"size() doesn't accept {type_name(value)}", pos)


class _Evaluator:
    def __init__(self, variables: Mapping[str, Value]) -> None:
        self.variables = variables

    def eval(self, node: Node, scope: Mapping[str, Value]) -> Value:
        match node:
            case Const(value=value):
                return value
            case Ident(name=name, pos=pos):
                if name in scope:
                    return scope[name]
                if name in self.variables:
                    return self.variables[name]
                raise EvalFailure(f"undeclared reference {name!r}", pos)
            case Select(operand=operand, field=field, pos=pos):
                target = self.eval(operand, scope)
                if not isinstance(target, dict):
                    raise EvalFailure(f"{type_name(target)} has no field {field!r}", pos)
                if field not in target:
                    raise EvalFailure(f"no such key {field!r}", pos)
                return target[field]
            case Presence(operand=operand, field=field, pos=pos):
                target = self.eval(operand, scope)
                if not isinstance(target, dict):
                    raise EvalFailure(f"has() needs a map, not {type_name(target)}", pos)
                return field in target
            case Index(operand=operand, index=index, pos=pos):
                return self.index(self.eval(operand, scope), self.eval(index, scope), pos)
            case Call(name=name, target=target, args=args, pos=pos):
                values = [self.eval(arg, scope) for arg in args]
                if target is not None:
                    values.insert(0, self.eval(target, scope))
                return self.call(name, values, pos)
            case ListExpr(items=items):
                return [self.eval(item, scope) for item in items]
            case MapExpr(entries=entries, pos=pos):
                result: dict[Key, Value] = {}
                for key_node, value_node in entries:
                    key = self.eval(key_node, scope)
                    if key is None or not isinstance(key, bool | int | str):
                        raise EvalFailure(f"map keys can't be {type_name(key)}", pos)
                    if _lookup(result, key)[0]:
                        raise EvalFailure("duplicate map key", pos)
                    result[key] = self.eval(value_node, scope)
                return result
            case Unary(op=op, operand=operand, pos=pos):
                value = self.eval(operand, scope)
                if op == "!":
                    if not isinstance(value, bool):
                        raise EvalFailure(f"'!' needs a bool, not {type_name(value)}", pos)
                    return not value
                if _is_int(value):
                    assert isinstance(value, int)
                    return _int64(-value, pos)
                if isinstance(value, float):
                    return -value
                raise EvalFailure(f"'-' needs a number, not {type_name(value)}", pos)
            case Binary(op="&&" | "||" as op, left=left, right=right, pos=pos):
                return self.logical(op, left, right, scope, pos)
            case Binary(op=op, left=left, right=right, pos=pos):
                a = self.eval(left, scope)
                b = self.eval(right, scope)
                return self.binary(op, a, b, pos)
            case Conditional(condition=condition, then=then, otherwise=otherwise, pos=pos):
                test = self.eval(condition, scope)
                if not isinstance(test, bool):
                    raise EvalFailure(f"'?' needs a bool condition, not {type_name(test)}", pos)
                return self.eval(then if test else otherwise, scope)
            case Comprehension():
                return self.comprehension(node, scope)

    def logical(
        self, op: str, left: Node, right: Node, scope: Mapping[str, Value], pos: int
    ) -> Value:
        # CEL's commutative logic: a decisive operand wins even if the other one errors.
        decisive = op == "||"
        results: list[bool | EvalFailure] = []
        for side in (left, right):
            try:
                value = self.eval(side, scope)
            except EvalFailure as failure:
                results.append(failure)
                continue
            if not isinstance(value, bool):
                results.append(EvalFailure(f"{op!r} needs bools, not {type_name(value)}", pos))
                continue
            if value is decisive:
                return decisive
            results.append(value)
        for result in results:
            if isinstance(result, EvalFailure):
                raise result
        return not decisive

    def binary(self, op: str, a: Value, b: Value, pos: int) -> Value:
        if op == "==":
            return _equals(a, b)
        if op == "!=":
            return not _equals(a, b)
        if op in {"<", "<=", ">", ">="}:
            order = _compare(a, b, pos)
            return {"<": order < 0, "<=": order <= 0, ">": order > 0, ">=": order >= 0}[op]
        if op == "in":
            if isinstance(b, list):
                return any(_equals(a, item) for item in b)
            if isinstance(b, dict):
                return _lookup(b, a)[0]
            raise EvalFailure(f"'in' needs a list or map, not {type_name(b)}", pos)
        return _arithmetic(op, a, b, pos)

    def index(self, target: Value, key: Value, pos: int) -> Value:
        if isinstance(target, list):
            if not _is_int(key):
                raise EvalFailure(f"list index must be an int, not {type_name(key)}", pos)
            assert isinstance(key, int)
            if not 0 <= key < len(target):
                raise EvalFailure("list index out of range", pos)
            return target[key]
        if isinstance(target, dict):
            found, value = _lookup(target, key)
            if not found:
                raise EvalFailure("no such key", pos)
            return value
        raise EvalFailure(f"{type_name(target)} can't be indexed", pos)

    def call(self, name: str, args: list[Value], pos: int) -> Value:
        match name:
            case "size":
                return _size(args[0], pos)
            case "int":
                return _to_int(args[0], pos)
            case "double":
                return _to_double(args[0], pos)
            case "string":
                return _to_string(args[0], pos)
            case "matches":
                return _matches(args[0], args[1], pos)
            case "startsWith" | "endsWith" | "contains":
                text, other = args
                if not (isinstance(text, str) and isinstance(other, str)):
                    raise EvalFailure(f"{name}() needs strings", pos)
                if name == "startsWith":
                    return text.startswith(other)
                if name == "endsWith":
                    return text.endswith(other)
                return other in text
            case _:  # pragma: no cover - the parser rejects unknown functions
                raise EvalFailure(f"unknown function {name!r}", pos)

    def comprehension(self, node: Comprehension, scope: Mapping[str, Value]) -> Value:
        target = self.eval(node.target, scope)
        if isinstance(target, list):
            elements: list[Value] = target
        elif isinstance(target, dict):
            elements = list(target)
        else:
            raise EvalFailure(
                f"{node.macro}() needs a list or map, not {type_name(target)}", node.pos
            )

        results: list[Value | EvalFailure] = []
        for element in elements:
            try:
                results.append(self.eval(node.body, {**scope, node.var: element}))
            except EvalFailure as failure:
                if node.macro in {"map", "filter"}:
                    raise
                results.append(failure)

        if node.macro == "map":
            return [r for r in results if not isinstance(r, EvalFailure)]
        for result in results:
            if not isinstance(result, EvalFailure | bool):
                raise EvalFailure(f"{node.macro}() needs a bool predicate", node.pos)
        if node.macro == "filter":
            return [e for e, keep in zip(elements, results, strict=True) if keep is True]
        if node.macro == "exists" and True in results:
            return True
        if node.macro == "all" and any(r is False for r in results):
            return False
        failures = [r for r in results if isinstance(r, EvalFailure)]
        if failures:
            raise failures[0]
        if node.macro == "exists_one":
            return results.count(True) == 1
        return node.macro == "all"


def evaluate(node: Node, variables: Mapping[str, Value]) -> Value:
    """Evaluate a syntax tree against converted variables.

    Raises:
        EvalFailure: On any evaluation error.
    """
    return _Evaluator(variables).eval(node, {})
