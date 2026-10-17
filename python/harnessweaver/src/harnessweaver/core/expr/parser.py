"""Precedence-climbing parser for cel-lite.

Precedence, lowest to highest (as in CEL)::

    c ? a : b          (right-associative)
    ||
    &&
    == != < <= > >= in
    + -
    * / %
    ! -                (prefix)
    .field  .method()  [index]  f()
"""

from collections.abc import Collection
from typing import Final

from harnessweaver.core.errors import ExpressionSyntaxError
from harnessweaver.core.expr.lexer import Token, TokenKind, tokenize
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
from harnessweaver.core.expr.values import INT64_MAX, INT64_MIN

__all__ = ["GLOBAL_FUNCTIONS", "MACROS", "MAX_DEPTH", "MAX_LENGTH", "METHODS", "parse"]

MAX_LENGTH: Final = 10_000
"""Longest accepted expression, in characters."""

MAX_DEPTH: Final = 64
"""Deepest accepted nesting."""

GLOBAL_FUNCTIONS: Final[dict[str, int]] = {
    "size": 1,
    "int": 1,
    "double": 1,
    "string": 1,
    "matches": 2,
}
"""Global functions and their arity. ``has()`` is a macro handled separately."""

METHODS: Final[dict[str, int]] = {
    "size": 0,
    "startsWith": 1,
    "endsWith": 1,
    "contains": 1,
    "matches": 1,
}
"""Receiver-style functions and their arity."""

MACROS: Final = frozenset({"exists", "all", "exists_one", "map", "filter"})
"""Comprehension macros: ``list.exists(x, predicate)``."""

_RELATIONS: Final = frozenset({"==", "!=", "<", "<=", ">", ">="})
_RESERVED: Final = frozenset(
    {
        "as", "break", "const", "continue", "else", "for", "function", "if", "import", "let",
        "loop", "package", "namespace", "return", "var", "void", "while",
    }
)  # fmt: skip


class _Parser:
    def __init__(self, source: str) -> None:
        self.source = source
        self.tokens = tokenize(source)
        self.index = 0
        self.depth = 0

    # -- helpers -----------------------------------------------------------------------------

    def error(self, message: str, pos: int | None = None) -> ExpressionSyntaxError:
        pos = self.peek().pos if pos is None else pos
        return ExpressionSyntaxError(
            f"{message} at position {pos}", expression=self.source, position=pos
        )

    def peek(self) -> Token:
        return self.tokens[self.index]

    def advance(self) -> Token:
        token = self.tokens[self.index]
        if token.kind is not TokenKind.EOF:
            self.index += 1
        return token

    def at_op(self, *ops: str) -> bool:
        token = self.peek()
        return token.kind is TokenKind.OP and token.text in ops

    def at_in(self) -> bool:
        token = self.peek()
        return token.kind is TokenKind.IDENT and token.text == "in"

    def expect_op(self, op: str) -> Token:
        if not self.at_op(op):
            found = self.peek().text or "end of expression"
            raise self.error(f"expected {op!r} but found {found!r}")
        return self.advance()

    def enter(self) -> None:
        self.depth += 1
        if self.depth > MAX_DEPTH:
            raise self.error(f"expression nests deeper than {MAX_DEPTH} levels")

    # -- grammar -----------------------------------------------------------------------------

    def parse(self) -> Node:
        node = self.expression()
        if self.peek().kind is not TokenKind.EOF:
            raise self.error(f"unexpected {self.peek().text!r}")
        return node

    def expression(self) -> Node:
        self.enter()
        condition = self.logical_or()
        if self.at_op("?"):
            pos = self.advance().pos
            then = self.logical_or()
            self.expect_op(":")
            otherwise = self.expression()
            condition = Conditional(condition, then, otherwise, pos)
        self.depth -= 1
        return condition

    def logical_or(self) -> Node:
        left = self.logical_and()
        while self.at_op("||"):
            pos = self.advance().pos
            left = Binary("||", left, self.logical_and(), pos)
        return left

    def logical_and(self) -> Node:
        left = self.relation()
        while self.at_op("&&"):
            pos = self.advance().pos
            left = Binary("&&", left, self.relation(), pos)
        return left

    def relation(self) -> Node:
        left = self.addition()
        while True:
            if self.at_op(*_RELATIONS):
                token = self.advance()
                left = Binary(token.text, left, self.addition(), token.pos)
            elif self.at_in():
                pos = self.advance().pos
                left = Binary("in", left, self.addition(), pos)
            else:
                return left

    def addition(self) -> Node:
        left = self.multiplication()
        while self.at_op("+", "-"):
            token = self.advance()
            left = Binary(token.text, left, self.multiplication(), token.pos)
        return left

    def multiplication(self) -> Node:
        left = self.unary()
        while self.at_op("*", "/", "%"):
            token = self.advance()
            left = Binary(token.text, left, self.unary(), token.pos)
        return left

    def unary(self) -> Node:
        return self.checked_int(self._unary())

    def _unary(self) -> Node:
        # Literals are range-checked only after negation is folded in, so the most
        # negative int64, -9223372036854775808, is accepted.
        if self.at_op("!", "-"):
            token = self.advance()
            self.enter()
            operand = self._unary()
            self.depth -= 1
            if token.text == "-" and isinstance(operand, Const):
                value = operand.value
                if isinstance(value, int | float) and not isinstance(value, bool):
                    return Const(-value, token.pos)
            return Unary(token.text, self.checked_int(operand), token.pos)
        return self.member()

    def checked_int(self, node: Node) -> Node:
        if (
            isinstance(node, Const)
            and isinstance(node.value, int)
            and not isinstance(node.value, bool)
            and not INT64_MIN <= node.value <= INT64_MAX
        ):
            raise self.error("integer literal is outside the 64-bit range", node.pos)
        return node

    def member(self) -> Node:
        node = self.primary()
        while True:
            if self.at_op("."):
                self.advance()
                name = self.peek()
                if name.kind is not TokenKind.IDENT:
                    raise self.error("expected a field or method name after '.'")
                self.advance()
                if self.at_op("("):
                    node = self.method_call(node, name)
                else:
                    node = Select(node, name.text, name.pos)
            elif self.at_op("["):
                pos = self.advance().pos
                index = self.expression()
                self.expect_op("]")
                node = Index(node, index, pos)
            else:
                return node

    def arguments(self) -> list[Node]:
        self.expect_op("(")
        args: list[Node] = []
        if not self.at_op(")"):
            args.append(self.expression())
            while self.at_op(","):
                self.advance()
                args.append(self.expression())
        self.expect_op(")")
        return args

    def method_call(self, target: Node, name: Token) -> Node:
        args = self.arguments()
        if name.text in MACROS:
            if len(args) != 2:
                raise self.error(f"{name.text}() takes a variable and an expression", name.pos)
            var = args[0]
            if not isinstance(var, Ident):
                raise self.error(f"the first argument of {name.text}() must be a name", name.pos)
            return Comprehension(name.text, target, var.name, args[1], name.pos)
        if name.text not in METHODS:
            raise self.error(f"unknown method {name.text!r}", name.pos)
        if len(args) != METHODS[name.text]:
            raise self.error(f"{name.text}() takes {METHODS[name.text]} argument(s)", name.pos)
        return Call(name.text, target, tuple(args), name.pos)

    def primary(self) -> Node:
        token = self.peek()
        if token.kind in {TokenKind.INT, TokenKind.DOUBLE, TokenKind.STRING}:
            self.advance()
            assert token.value is not None
            return Const(token.value, token.pos)
        if token.kind is TokenKind.IDENT:
            self.advance()
            if token.text in {"true", "false"}:
                return Const(token.text == "true", token.pos)
            if token.text == "null":
                return Const(None, token.pos)
            if token.text in _RESERVED or token.text == "in":
                raise self.error(f"{token.text!r} is a reserved word", token.pos)
            if self.at_op("("):
                return self.global_call(token)
            return Ident(token.text, token.pos)
        if self.at_op("("):
            self.advance()
            node = self.expression()
            self.expect_op(")")
            return node
        if self.at_op("["):
            return self.list_literal()
        if self.at_op("{"):
            return self.map_literal()
        found = token.text or "end of expression"
        raise self.error(f"unexpected {found!r}")

    def global_call(self, name: Token) -> Node:
        args = self.arguments()
        if name.text == "has":
            if len(args) != 1 or not isinstance(args[0], Select):
                raise self.error("has() takes one field selection, e.g. has(a.b)", name.pos)
            return Presence(args[0].operand, args[0].field, name.pos)
        if name.text not in GLOBAL_FUNCTIONS:
            raise self.error(f"unknown function {name.text!r}", name.pos)
        if len(args) != GLOBAL_FUNCTIONS[name.text]:
            arity = GLOBAL_FUNCTIONS[name.text]
            raise self.error(f"{name.text}() takes {arity} argument(s)", name.pos)
        return Call(name.text, None, tuple(args), name.pos)

    def list_literal(self) -> Node:
        pos = self.advance().pos
        items: list[Node] = []
        while not self.at_op("]"):
            items.append(self.expression())
            if not self.at_op(","):
                break
            self.advance()
        self.expect_op("]")
        return ListExpr(tuple(items), pos)

    def map_literal(self) -> Node:
        pos = self.advance().pos
        entries: list[tuple[Node, Node]] = []
        while not self.at_op("}"):
            key = self.expression()
            self.expect_op(":")
            entries.append((key, self.expression()))
            if not self.at_op(","):
                break
            self.advance()
        self.expect_op("}")
        return MapExpr(tuple(entries), pos)


def _check_declared(node: Node, declared: Collection[str], bound: frozenset[str]) -> None:
    match node:
        case Ident(name=name, pos=pos):
            if name not in bound and name not in declared:
                raise ExpressionSyntaxError(
                    f"undeclared reference {name!r} at position {pos}", position=pos
                )
        case Const():
            pass
        case Select(operand=operand) | Presence(operand=operand):
            _check_declared(operand, declared, bound)
        case Index(operand=operand, index=index):
            _check_declared(operand, declared, bound)
            _check_declared(index, declared, bound)
        case Call(target=target, args=args):
            if target is not None:
                _check_declared(target, declared, bound)
            for arg in args:
                _check_declared(arg, declared, bound)
        case ListExpr(items=items):
            for item in items:
                _check_declared(item, declared, bound)
        case MapExpr(entries=entries):
            for key, value in entries:
                _check_declared(key, declared, bound)
                _check_declared(value, declared, bound)
        case Unary(operand=operand):
            _check_declared(operand, declared, bound)
        case Binary(left=left, right=right):
            _check_declared(left, declared, bound)
            _check_declared(right, declared, bound)
        case Conditional(condition=condition, then=then, otherwise=otherwise):
            for part in (condition, then, otherwise):
                _check_declared(part, declared, bound)
        case Comprehension(target=target, var=var, body=body):
            _check_declared(target, declared, bound)
            _check_declared(body, declared, bound | {var})


def parse(source: str, *, declared: Collection[str] | None = None) -> Node:
    """Parse a cel-lite expression into a syntax tree.

    Args:
        source: The expression text.
        declared: If given, the only variable names the expression may use.

    Raises:
        ExpressionSyntaxError: If the expression is malformed, too long or too deep,
            calls an unknown function, or uses an undeclared variable.
    """
    if len(source) > MAX_LENGTH:
        raise ExpressionSyntaxError(f"expression is longer than {MAX_LENGTH} characters")
    node = _Parser(source).parse()
    if declared is not None:
        _check_declared(node, declared, frozenset())
    return node
