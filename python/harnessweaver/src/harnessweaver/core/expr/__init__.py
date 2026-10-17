"""cel-lite: the built-in expression language (DESIGNS ADR-0004).

cel-lite is a subset of `CEL <https://cel.dev>`_ used for policy rules, routing
rules, approval conditions and business rules. Python and TypeScript implement
it from the same fixtures (suite ``expr``), and the full-CEL plugin can replace
it where needed.

>>> compile_expression("args.amount_usd > 100").evaluate({"args": {"amount_usd": 250}})
True

It never calls ``eval`` or touches Python objects (RULES S4): variables are
converted to plain JSON-like values first.
"""

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field

from harnessweaver.core.errors import ExpressionEvalError
from harnessweaver.core.expr.evaluator import EvalFailure, evaluate, format_double
from harnessweaver.core.expr.nodes import Node
from harnessweaver.core.expr.parser import GLOBAL_FUNCTIONS, MACROS, METHODS, parse
from harnessweaver.core.expr.values import ConversionError, Value, from_host, type_name

__all__ = [
    "GLOBAL_FUNCTIONS",
    "MACROS",
    "METHODS",
    "Expression",
    "Value",
    "compile_expression",
    "format_double",
]


@dataclass(frozen=True, slots=True)
class Expression:
    """A compiled cel-lite expression. Compile once, evaluate many times."""

    source: str
    _root: Node = field(repr=False)

    def evaluate(self, variables: Mapping[str, object] | None = None) -> Value:
        """Evaluate against ``variables`` (plain data or Pydantic models).

        Raises:
            ExpressionEvalError: If evaluation fails or a variable can't be converted.
        """
        try:
            converted = {name: from_host(value) for name, value in (variables or {}).items()}
        except ConversionError as exc:
            raise ExpressionEvalError(str(exc), expression=self.source) from None
        try:
            return evaluate(self._root, converted)
        except EvalFailure as failure:
            raise ExpressionEvalError(
                f"{failure.message} at position {failure.pos}",
                expression=self.source,
                position=failure.pos,
            ) from None

    def evaluate_bool(self, variables: Mapping[str, object] | None = None) -> bool:
        """Evaluate a predicate.

        Raises:
            ExpressionEvalError: If evaluation fails or the result isn't a bool.
        """
        result = self.evaluate(variables)
        if not isinstance(result, bool):
            raise ExpressionEvalError(
                f"expected a bool result, got {type_name(result)}", expression=self.source
            )
        return result


def compile_expression(source: str, *, declared: Iterable[str] | None = None) -> Expression:
    """Compile a cel-lite expression.

    Args:
        source: The expression text.
        declared: If given, the only variable names the expression may use. Specs
            pass these so a typo fails when the harness loads (R4).

    Raises:
        ExpressionSyntaxError: If the expression is invalid.
    """
    names = None if declared is None else frozenset(declared)
    return Expression(source, parse(source, declared=names))
