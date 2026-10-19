"""Unit tests for the JSON Schema subset's own checks and the rate limiter (ADR-0026)."""

from typing import Any

import pytest

from harnessweaver.core.jsonschema import SchemaError, check_schema, validate
from harnessweaver.modules.tools import RateLimiter


@pytest.mark.parametrize(
    ("schema", "message"),
    [
        ({"properties": []}, "properties: must be an object"),
        ({"properties": {"a": 3}}, "properties.a: must be a schema"),
        ({"pattern": 3}, "pattern: must be a string"),
        ({"pattern": "("}, "isn't a valid regular expression"),
        ({"anyOf": []}, "anyOf: must be a non-empty list"),
        ({"required": "a"}, "required: must be a list of names"),
        ({"enum": "a"}, "enum: must be a list"),
        ({"multipleOf": 0}, "multipleOf: must be a positive number"),
        ({"minimum": "1"}, "minimum: must be a number"),
        ({"$ref": 3}, r"\$ref: must be a string"),
        ({"$ref": "#/$defs/missing"}, "must name a definition"),
        ({"$defs": {"x": {"if": {}}}}, r"\$defs.x.if: keyword 'if' isn't supported"),
        ({"type": []}, "unknown type"),
        ({"items": {"type": "decimal"}}, "items.type: unknown type"),
    ],
)
def test_malformed_schemas_fail(schema: dict[str, Any], message: str) -> None:
    with pytest.raises(SchemaError, match=message):
        check_schema(schema)


def test_boolean_subschemas() -> None:
    schema: dict[str, Any] = {
        "type": "object",
        "properties": {"open": True, "never": False},
        "additionalProperties": True,
    }
    check_schema(schema)
    assert validate({"open": 1, "other": 2}, schema) == []
    assert validate({"never": 1}, schema) == ["never: isn't allowed"]


@pytest.mark.parametrize(
    ("schema", "value", "location"),
    [
        ({"type": "array", "maxItems": 1}, [1, 2], "(root)"),
        ({"type": "string", "maxLength": 1}, "ab", "(root)"),
        ({"type": "number", "maximum": 1}, 2, "(root)"),
        ({"type": "number", "exclusiveMinimum": 1}, 1, "(root)"),
        ({"type": "object", "maxProperties": 1}, {"a": 1, "b": 2}, "(root)"),
        ({"type": "array", "items": {"type": "integer"}}, [1, "x"], "[1]"),
        ({"allOf": [{"type": "number"}, {"minimum": 5}]}, 3, "(root)"),
    ],
)
def test_more_limits(schema: dict[str, Any], value: Any, location: str) -> None:
    check_schema(schema)
    problems = validate(value, schema)
    assert [p.split(": ", 1)[0] for p in problems] == [location]


def test_a_reservation_given_back_frees_its_place() -> None:
    limiter = RateLimiter()
    key = ("lookup", "principal", "alice")
    first = limiter.acquire([(key, 1, 60.0)], now=100.0)
    assert first is not None
    assert limiter.acquire([(key, 1, 60.0)], now=101.0) is None
    limiter.release(first)
    assert limiter.acquire([(key, 1, 60.0)], now=102.0) is not None
    assert limiter.acquire([(key, 1, 60.0)], now=200.0) is not None  # the window slid on


def test_a_call_waiting_for_approval_doesnt_use_up_the_limit() -> None:
    limiter = RateLimiter()
    key = ("refund", "tenant", "acme")
    held = limiter.acquire([(key, 1, 60.0), (("refund", "principal", "a"), 5, 60.0)], now=1.0)
    assert held is not None
    limiter.release(held)
    limiter.release(held)  # releasing twice is harmless
    assert limiter.acquire([(key, 1, 60.0)], now=2.0) is not None
