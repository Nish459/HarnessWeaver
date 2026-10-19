"""Checking that an expression uses only the names it may use (R4)."""

from collections.abc import Collection

from harnessweaver.core.errors import ExpressionSyntaxError
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

__all__ = ["check_declared"]


def check_declared(node: Node, declared: Collection[str], bound: frozenset[str]) -> None:
    match node:
        case Ident(name=name, pos=pos):
            if name not in bound and name not in declared:
                raise ExpressionSyntaxError(
                    f"undeclared reference {name!r} at position {pos}", position=pos
                )
        case Const():
            pass
        case Select(operand=operand) | Presence(operand=operand):
            check_declared(operand, declared, bound)
        case Index(operand=operand, index=index):
            check_declared(operand, declared, bound)
            check_declared(index, declared, bound)
        case Call(target=target, args=args):
            if target is not None:
                check_declared(target, declared, bound)
            for arg in args:
                check_declared(arg, declared, bound)
        case ListExpr(items=items):
            for item in items:
                check_declared(item, declared, bound)
        case MapExpr(entries=entries):
            for key, value in entries:
                check_declared(key, declared, bound)
                check_declared(value, declared, bound)
        case Unary(operand=operand):
            check_declared(operand, declared, bound)
        case Binary(left=left, right=right):
            check_declared(left, declared, bound)
            check_declared(right, declared, bound)
        case Conditional(condition=condition, then=then, otherwise=otherwise):
            for part in (condition, then, otherwise):
                check_declared(part, declared, bound)
        case Comprehension(target=target, var=var, body=body):
            check_declared(target, declared, bound)
            check_declared(body, declared, bound | {var})
