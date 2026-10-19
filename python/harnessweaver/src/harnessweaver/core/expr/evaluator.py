"""Evaluator for cel-lite syntax trees.

Semantics follow CEL where cel-lite overlaps it:

* ``&&`` and ``||`` absorb errors: ``error || true`` is ``true``.
* Ints are 64-bit and overflow is an error; int division truncates toward zero.
* Mixing ints and doubles in arithmetic gives a double (CEL would refuse; this
  is a documented relaxation, see DESIGNS ADR-0004).
* Values of different types are never equal; comparing them is an error.
* Errors name types and keys, never values (R9).
"""

from collections.abc import Mapping

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
from harnessweaver.core.expr.operations import (
    EvalFailure,
    arithmetic,
    compare,
    equals,
    int64,
    is_int,
    lookup,
    matches,
    size,
    to_double,
    to_int,
    to_string,
)
from harnessweaver.core.expr.values import Key, Value, type_name


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
                    if lookup(result, key)[0]:
                        raise EvalFailure("duplicate map key", pos)
                    result[key] = self.eval(value_node, scope)
                return result
            case Unary(op=op, operand=operand, pos=pos):
                value = self.eval(operand, scope)
                if op == "!":
                    if not isinstance(value, bool):
                        raise EvalFailure(f"'!' needs a bool, not {type_name(value)}", pos)
                    return not value
                if is_int(value):
                    assert isinstance(value, int)
                    return int64(-value, pos)
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
            return equals(a, b)
        if op == "!=":
            return not equals(a, b)
        if op in {"<", "<=", ">", ">="}:
            order = compare(a, b, pos)
            return {"<": order < 0, "<=": order <= 0, ">": order > 0, ">=": order >= 0}[op]
        if op == "in":
            if isinstance(b, list):
                return any(equals(a, item) for item in b)
            if isinstance(b, dict):
                return lookup(b, a)[0]
            raise EvalFailure(f"'in' needs a list or map, not {type_name(b)}", pos)
        return arithmetic(op, a, b, pos)

    def index(self, target: Value, key: Value, pos: int) -> Value:
        if isinstance(target, list):
            if not is_int(key):
                raise EvalFailure(f"list index must be an int, not {type_name(key)}", pos)
            assert isinstance(key, int)
            if not 0 <= key < len(target):
                raise EvalFailure("list index out of range", pos)
            return target[key]
        if isinstance(target, dict):
            found, value = lookup(target, key)
            if not found:
                raise EvalFailure("no such key", pos)
            return value
        raise EvalFailure(f"{type_name(target)} can't be indexed", pos)

    def call(self, name: str, args: list[Value], pos: int) -> Value:
        match name:
            case "size":
                return size(args[0], pos)
            case "int":
                return to_int(args[0], pos)
            case "double":
                return to_double(args[0], pos)
            case "string":
                return to_string(args[0], pos)
            case "matches":
                return matches(args[0], args[1], pos)
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
