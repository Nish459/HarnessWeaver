"""Python runners for the shared conformance suites."""

from datetime import timedelta
from typing import Any

import pytest
from pydantic import TypeAdapter

from harnessweaver.core.durations import duration_ms, format_duration, parse_duration
from harnessweaver.core.errors import ExpressionEvalError, ExpressionSyntaxError
from harnessweaver.core.expr import compile_expression
from harnessweaver.core.expr.values import type_name
from harnessweaver.core.hooks import Band, HookPoint, execution_order
from harnessweaver.core.outcomes import Outcome, most_severe, severity
from harnessweaver.core.semver import Version, VersionRange

_OUTCOME = TypeAdapter[Outcome](Outcome)


def _strict_equal(actual: Any, expected: Any) -> bool:
    """Deep equality that keeps bools apart from numbers (Python's True == 1 doesn't apply)."""
    if isinstance(expected, bool) or isinstance(actual, bool):
        return type(actual) is type(expected) and actual == expected
    if isinstance(expected, int | float) and isinstance(actual, int | float):
        return actual == expected
    if isinstance(expected, list):
        return (
            isinstance(actual, list)
            and len(actual) == len(expected)
            and all(_strict_equal(a, e) for a, e in zip(actual, expected, strict=True))
        )
    if isinstance(expected, dict):
        return (
            isinstance(actual, dict)
            and actual.keys() == expected.keys()
            and all(_strict_equal(actual[k], expected[k]) for k in expected)
        )
    return type(actual) is type(expected) and actual == expected


@pytest.mark.conformance_suite("durations")
def test_durations(case: dict[str, Any]) -> None:
    expect = case["expect"]
    if expect.get("error"):
        with pytest.raises(ValueError):
            parse_duration(case["input"])
        return
    parsed = parse_duration(case["input"])
    assert duration_ms(parsed) == expect["ms"]
    assert format_duration(parsed) == expect["canonical"]
    assert parse_duration(expect["canonical"]) == parsed == timedelta(milliseconds=expect["ms"])


@pytest.mark.conformance_suite("semver")
def test_semver(case: dict[str, Any]) -> None:
    expect = case["expect"]
    if "version" in case:
        if isinstance(expect, dict) and expect.get("error"):
            with pytest.raises(ValueError):
                Version.parse(case["version"])
        else:
            assert str(Version.parse(case["version"])) == expect["canonical"]
    elif "compare" in case:
        a, b = (Version.parse(v) for v in case["compare"])
        assert (a > b) - (a < b) == expect
        assert (b > a) - (b < a) == -expect
    else:
        if expect.get("error"):
            with pytest.raises(ValueError):
                VersionRange.parse(case["range"])
            return
        version_range = VersionRange.parse(case["range"])
        for version in expect["matches"]:
            assert version_range.contains(version), f"{case['range']} should match {version}"
        for version in expect["rejects"]:
            assert not version_range.contains(version), f"{case['range']} should reject {version}"


@pytest.mark.conformance_suite("outcomes")
def test_outcomes(case: dict[str, Any]) -> None:
    expect = case["expect"]
    if "outcome" in case:
        assert severity(_OUTCOME.validate_python(case["outcome"])) == expect["severity"]
        return
    outcomes = [_OUTCOME.validate_python(o) for o in case["outcomes"]]
    result = most_severe(outcomes)
    assert result.kind == expect["kind"]
    if expect["index"] is None:
        assert result not in outcomes or not outcomes
    else:
        assert result is outcomes[expect["index"]]


@pytest.mark.conformance_suite("hook_order")
def test_hook_order(case: dict[str, Any]) -> None:
    if "directions" in case:
        assert {hook.value for hook in HookPoint} == set(case["directions"])
        for name, direction in case["directions"].items():
            assert HookPoint(name).direction.value == direction
        return
    ordered = execution_order(
        case["middleware"], HookPoint(case["hook"]), lambda m: Band(m["band"])
    )
    assert [m["name"] for m in ordered] == case["expect"]


@pytest.mark.conformance_suite("expr")
def test_expr(case: dict[str, Any]) -> None:
    expect = case["expect"]
    variables = case.get("vars", {})
    if expect.get("error") == "syntax":
        with pytest.raises(ExpressionSyntaxError):
            compile_expression(case["expr"])
        return
    expression = compile_expression(case["expr"])
    if expect.get("error") == "eval":
        with pytest.raises(ExpressionEvalError):
            expression.evaluate(variables)
        return
    result = expression.evaluate(variables)
    assert _strict_equal(result, expect["value"]), f"{result!r} != {expect['value']!r}"
    if "type" in expect:
        assert type_name(result) == expect["type"]
