import pytest
from pydantic import BaseModel

from harnessweaver.core.errors import ExpressionEvalError, ExpressionSyntaxError
from harnessweaver.core.expr import compile_expression
from harnessweaver.core.expr.parser import MAX_DEPTH, MAX_LENGTH


def test_declared_variables_are_checked_at_compile_time() -> None:
    compile_expression("args.x > 1 && [1].exists(v, v > 0)", declared={"args"})
    with pytest.raises(ExpressionSyntaxError, match="undeclared reference 'arg'"):
        compile_expression("arg.x > 1", declared={"args"})


def test_pydantic_models_and_tuples_are_converted() -> None:
    class Args(BaseModel):
        amount_usd: float
        tags: tuple[str, ...]

    expression = compile_expression("args.amount_usd > 100 && 'vip' in args.tags")
    assert expression.evaluate_bool({"args": Args(amount_usd=250, tags=("vip",))})


def test_unsupported_variables_are_rejected() -> None:
    with pytest.raises(ExpressionEvalError, match="unsupported value"):
        compile_expression("x").evaluate({"x": object()})
    with pytest.raises(ExpressionEvalError, match="64-bit"):
        compile_expression("x").evaluate({"x": 2**70})


def test_evaluate_bool_requires_a_bool() -> None:
    with pytest.raises(ExpressionEvalError, match="expected a bool"):
        compile_expression("1 + 1").evaluate_bool()


def test_errors_report_positions_but_not_values() -> None:
    with pytest.raises(ExpressionEvalError) as caught:
        compile_expression("secret.missing").evaluate({"secret": {"token": "sk-test-123"}})
    assert caught.value.details["position"] == 7  # the field name
    assert "sk-test-123" not in str(caught.value)


def test_limits_on_length_and_depth() -> None:
    with pytest.raises(ExpressionSyntaxError, match="longer than"):
        compile_expression("1" * (MAX_LENGTH + 1))
    with pytest.raises(ExpressionSyntaxError, match="nests deeper"):
        compile_expression("(" * (MAX_DEPTH + 1) + "1" + ")" * (MAX_DEPTH + 1))
    with pytest.raises(ExpressionSyntaxError, match="nests deeper"):
        compile_expression("!" * (MAX_DEPTH + 1) + "true")


def test_never_uses_python_eval() -> None:
    # Python syntax and dunder access are just unknown names or syntax errors here (S4).
    with pytest.raises(ExpressionSyntaxError):
        compile_expression("__import__('os')")
    with pytest.raises(ExpressionEvalError):
        compile_expression("x.__class__").evaluate({"x": {}})


@pytest.mark.parametrize(
    ("source", "message"),
    [
        (r"'\xZZ'", r"invalid \\x escape"),
        (r"'\U0010FFFF' + '\uD800'", "not a valid code point"),
        ("'abc\\", "unterminated string"),
        ("'line\nbreak'", "unterminated string"),
        ("1 @ 2", "unexpected character '@'"),
        ("1.", "invalid number"),
        ("(1", r"expected '\)'"),
        ("{'a' 1}", "expected ':'"),
        ("a.1", "expected a field or method name"),
        ("1 2", "unexpected '2'"),
        ("", "unexpected 'end of expression'"),
    ],
)
def test_syntax_errors(source: str, message: str) -> None:
    with pytest.raises(ExpressionSyntaxError, match=message):
        compile_expression(source)


def test_comment_at_the_end_without_a_newline() -> None:
    assert compile_expression("1 + 1 // done").evaluate() == 2


def test_declared_names_are_checked_in_every_kind_of_node() -> None:
    declared = {"a", "b"}
    source = "{a: [b[0], -a.x]}.size() > 0 && has(a.y) ? a.z.startsWith('q') : b.map(v, v + a.w)"
    compile_expression(source, declared=declared)
    for typo in [
        "{c: 1}",
        "[c]",
        "-c",
        "a[c]",
        "c.size()",
        "has(c.x)",
        "true ? c : 1",
        "b.map(v, c)",
    ]:
        with pytest.raises(ExpressionSyntaxError, match="undeclared reference 'c'"):
            compile_expression(typo, declared=declared)
