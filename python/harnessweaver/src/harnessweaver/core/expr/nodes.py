"""The cel-lite syntax tree."""

from dataclasses import dataclass

from harnessweaver.core.expr.values import Value

__all__ = [
    "Binary",
    "Call",
    "Comprehension",
    "Conditional",
    "Const",
    "Ident",
    "Index",
    "ListExpr",
    "MapExpr",
    "Node",
    "Presence",
    "Select",
    "Unary",
]


@dataclass(frozen=True, slots=True)
class Const:
    value: Value
    pos: int


@dataclass(frozen=True, slots=True)
class Ident:
    name: str
    pos: int


@dataclass(frozen=True, slots=True)
class Select:
    operand: "Node"
    field: str
    pos: int


@dataclass(frozen=True, slots=True)
class Presence:
    """``has(operand.field)``."""

    operand: "Node"
    field: str
    pos: int


@dataclass(frozen=True, slots=True)
class Index:
    operand: "Node"
    index: "Node"
    pos: int


@dataclass(frozen=True, slots=True)
class Call:
    """A global function call (``target is None``) or a method call on ``target``."""

    name: str
    target: "Node | None"
    args: tuple["Node", ...]
    pos: int


@dataclass(frozen=True, slots=True)
class ListExpr:
    items: tuple["Node", ...]
    pos: int


@dataclass(frozen=True, slots=True)
class MapExpr:
    entries: tuple[tuple["Node", "Node"], ...]
    pos: int


@dataclass(frozen=True, slots=True)
class Unary:
    op: str
    operand: "Node"
    pos: int


@dataclass(frozen=True, slots=True)
class Binary:
    op: str
    left: "Node"
    right: "Node"
    pos: int


@dataclass(frozen=True, slots=True)
class Conditional:
    condition: "Node"
    then: "Node"
    otherwise: "Node"
    pos: int


@dataclass(frozen=True, slots=True)
class Comprehension:
    """A macro such as ``target.exists(var, body)``."""

    macro: str
    target: "Node"
    var: str
    body: "Node"
    pos: int


type Node = (
    Const
    | Ident
    | Select
    | Presence
    | Index
    | Call
    | ListExpr
    | MapExpr
    | Unary
    | Binary
    | Conditional
    | Comprehension
)
