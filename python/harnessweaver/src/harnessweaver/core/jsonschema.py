"""A small JSON Schema (2020-12) validator for tool arguments (ADR-0026).

The core may not depend on ``jsonschema`` (R6), and tool arguments need only a
subset, which the TypeScript SDK implements from the same fixtures (suite
``governor``). Supported keywords:

* any value: ``type`` (a name or a list of names), ``enum``, ``const``
* objects: ``properties``, ``required``, ``additionalProperties`` (``false`` or a
  schema), ``minProperties``, ``maxProperties``
* arrays: ``items``, ``minItems``, ``maxItems``, ``uniqueItems``
* strings: ``minLength``, ``maxLength``, ``pattern`` (searched, not anchored)
* numbers: ``minimum``, ``maximum``, ``exclusiveMinimum``, ``exclusiveMaximum``,
  ``multipleOf``
* composition: ``allOf``, ``anyOf``, ``oneOf``, ``not``
* references to the same document: ``$ref`` to ``#/$defs/<name>`` (or
  ``#/definitions/<name>``)

Annotations such as ``title``, ``description``, ``default``, ``examples`` and
``format`` are ignored. Any other keyword fails :func:`check_schema`, so a
schema never validates less than it says (R4). Problems name the location and
the rule, never the value (R9).
"""

import math
import operator
import re
from collections.abc import Callable, Mapping
from typing import Final, cast

from pydantic import JsonValue

from harnessweaver.core.digests import canonical_json

__all__ = ["SchemaError", "check_schema", "validate"]

_ANNOTATIONS: Final = frozenset(
    {
        "$schema", "$id", "$comment", "$defs", "definitions", "title", "description",
        "default", "examples", "format", "deprecated", "readOnly", "writeOnly",
        "contentMediaType", "contentEncoding",
    }
)  # fmt: skip
_KEYWORDS: Final = frozenset(
    {
        "type", "enum", "const", "properties", "required", "additionalProperties",
        "minProperties", "maxProperties", "items", "minItems", "maxItems", "uniqueItems",
        "minLength", "maxLength", "pattern", "minimum", "maximum", "exclusiveMinimum",
        "exclusiveMaximum", "multipleOf", "allOf", "anyOf", "oneOf", "not", "$ref",
    }
)  # fmt: skip
_TYPES: Final = frozenset({"object", "array", "string", "integer", "number", "boolean", "null"})

type Schema = Mapping[str, JsonValue]

_NUMBER_CHECKS: Final[tuple[tuple[str, Callable[[float, float], bool], str], ...]] = (
    ("minimum", operator.ge, "at least"),
    ("maximum", operator.le, "at most"),
    ("exclusiveMinimum", operator.gt, "more than"),
    ("exclusiveMaximum", operator.lt, "less than"),
)


class SchemaError(ValueError):
    """A schema that is malformed or uses a keyword outside the supported subset."""


def _where(path: str) -> str:
    return path or "(root)"


def _is_number(value: JsonValue) -> bool:
    return isinstance(value, int | float) and not isinstance(value, bool)


def _type_matches(name: str, value: JsonValue) -> bool:
    match name:
        case "object":
            return isinstance(value, dict)
        case "array":
            return isinstance(value, list)
        case "string":
            return isinstance(value, str)
        case "boolean":
            return isinstance(value, bool)
        case "null":
            return value is None
        case "number":
            return _is_number(value)
        case _:  # integer: a number with no fractional part
            return _is_number(value) and float(cast(float, value)).is_integer()


def _schema_at(root: Schema, ref: str, path: str) -> Schema:
    for prefix in ("#/$defs/", "#/definitions/"):
        if ref.startswith(prefix):
            defs = root.get(prefix[2:-1])
            target = defs.get(ref[len(prefix) :]) if isinstance(defs, dict) else None
            if isinstance(target, dict):
                return target
    raise SchemaError(f"{_where(path)}: $ref {ref!r} must name a definition in #/$defs")


def check_schema(schema: Schema, *, _root: Schema | None = None, _path: str = "") -> None:
    """Check that ``schema`` is well formed and uses only the supported keywords.

    Raises:
        SchemaError: Naming the first problem's location.
    """
    root = _root if _root is not None else schema
    for key, value in schema.items():
        where = f"{_path}.{key}" if _path else key
        if key in _ANNOTATIONS:
            if key in ("$defs", "definitions") and isinstance(value, dict):
                for name, sub in value.items():
                    _check_sub(sub, root, f"{where}.{name}")
            continue
        if key not in _KEYWORDS:
            raise SchemaError(f"{where}: keyword {key!r} isn't supported")
        if key == "type":
            names = value if isinstance(value, list) else [value]
            if not names or not all(isinstance(n, str) and n in _TYPES for n in names):
                raise SchemaError(f"{where}: unknown type")
        elif key == "pattern":
            if not isinstance(value, str):
                raise SchemaError(f"{where}: must be a string")
            try:
                re.compile(value)
            except re.error:
                raise SchemaError(f"{where}: isn't a valid regular expression") from None
        elif key == "properties":
            if not isinstance(value, dict):
                raise SchemaError(f"{where}: must be an object")
            for name, sub in value.items():
                _check_sub(sub, root, f"{where}.{name}")
        elif key in ("items", "not") or (key == "additionalProperties" and value is not False):
            if key == "additionalProperties" and value is True:
                continue
            _check_sub(value, root, where)
        elif key in ("allOf", "anyOf", "oneOf"):
            if not isinstance(value, list) or not value:
                raise SchemaError(f"{where}: must be a non-empty list of schemas")
            for index, sub in enumerate(value):
                _check_sub(sub, root, f"{where}[{index}]")
        elif key == "$ref":
            if not isinstance(value, str):
                raise SchemaError(f"{where}: must be a string")
            _schema_at(root, value, where)
        elif key == "required":
            if not isinstance(value, list) or not all(isinstance(n, str) for n in value):
                raise SchemaError(f"{where}: must be a list of names")
        elif key == "enum":
            if not isinstance(value, list):
                raise SchemaError(f"{where}: must be a list")
        elif key in ("multipleOf",):
            if not _is_number(value) or cast(float, value) <= 0:
                raise SchemaError(f"{where}: must be a positive number")
        elif key not in ("const", "uniqueItems", "additionalProperties") and not _is_number(value):
            raise SchemaError(f"{where}: must be a number")


def _check_sub(value: JsonValue, root: Schema, path: str) -> None:
    if isinstance(value, bool):
        return
    if not isinstance(value, dict):
        raise SchemaError(f"{_where(path)}: must be a schema (an object or a boolean)")
    check_schema(value, _root=root, _path=path)


def validate(value: JsonValue, schema: Schema) -> list[str]:
    """Check ``value`` against ``schema``. Returns the problems; empty means valid.

    The schema should have passed :func:`check_schema`.
    """
    problems: list[str] = []
    _validate(value, schema, schema, "", problems)
    return problems


def _validate(
    value: JsonValue, schema: JsonValue | Schema, root: Schema, path: str, problems: list[str]
) -> None:
    if schema is True:
        return
    if schema is False:
        problems.append(f"{_where(path)}: isn't allowed")
        return
    if not isinstance(schema, dict):
        return
    where = _where(path)
    ref = schema.get("$ref")
    if isinstance(ref, str):
        _validate(value, _schema_at(root, ref, path), root, path, problems)
    kind = schema.get("type")
    if kind is not None:
        names = kind if isinstance(kind, list) else [kind]
        if not any(isinstance(n, str) and _type_matches(n, value) for n in names):
            problems.append(f"{where}: must be {' or '.join(str(n) for n in names)}")
            return
    if "const" in schema and canonical_json(value) != canonical_json(schema["const"]):
        problems.append(f"{where}: must be the constant value")
    enum = schema.get("enum")
    if isinstance(enum, list) and canonical_json(value) not in {canonical_json(e) for e in enum}:
        problems.append(f"{where}: must be one of the allowed values")
    if isinstance(value, dict):
        _validate_object(value, schema, root, path, problems)
    elif isinstance(value, list):
        _validate_array(value, schema, root, path, problems)
    elif isinstance(value, str):
        _validate_string(value, schema, where, problems)
    elif _is_number(value):
        _validate_number(cast(float, value), schema, where, problems)
    _validate_composition(value, schema, root, path, problems)


def _validate_object(
    value: dict[str, JsonValue], schema: Schema, root: Schema, path: str, problems: list[str]
) -> None:
    where = _where(path)
    properties = schema.get("properties")
    known = properties if isinstance(properties, dict) else {}
    required = schema.get("required")
    for name in required if isinstance(required, list) else []:
        if isinstance(name, str) and name not in value:
            problems.append(f"{f'{path}.{name}' if path else name}: is required")
    extra = schema.get("additionalProperties", True)
    for name, item in value.items():
        child = f"{path}.{name}" if path else name
        if name in known:
            _validate(item, known[name], root, child, problems)
        elif extra is False:
            problems.append(f"{child}: isn't an allowed property")
        else:
            _validate(item, extra, root, child, problems)
    lowest, highest = schema.get("minProperties"), schema.get("maxProperties")
    if _is_number(lowest) and len(value) < cast(float, lowest):
        problems.append(f"{where}: must have at least {lowest} properties")
    if _is_number(highest) and len(value) > cast(float, highest):
        problems.append(f"{where}: must have at most {highest} properties")


def _validate_array(
    value: list[JsonValue], schema: Schema, root: Schema, path: str, problems: list[str]
) -> None:
    where = _where(path)
    items = schema.get("items")
    if items is not None:
        for index, item in enumerate(value):
            _validate(item, items, root, f"{path}[{index}]", problems)
    lowest, highest = schema.get("minItems"), schema.get("maxItems")
    if _is_number(lowest) and len(value) < cast(float, lowest):
        problems.append(f"{where}: must have at least {lowest} items")
    if _is_number(highest) and len(value) > cast(float, highest):
        problems.append(f"{where}: must have at most {highest} items")
    if schema.get("uniqueItems") is True:
        texts = [canonical_json(item) for item in value]
        if len(set(texts)) != len(texts):
            problems.append(f"{where}: items must be unique")


def _validate_string(value: str, schema: Schema, where: str, problems: list[str]) -> None:
    length = len(value)
    lowest, highest = schema.get("minLength"), schema.get("maxLength")
    if _is_number(lowest) and length < cast(float, lowest):
        problems.append(f"{where}: must be at least {lowest} characters")
    if _is_number(highest) and length > cast(float, highest):
        problems.append(f"{where}: must be at most {highest} characters")
    pattern = schema.get("pattern")
    if isinstance(pattern, str) and re.search(pattern, value) is None:
        problems.append(f"{where}: must match the pattern")


def _validate_number(value: float, schema: Schema, where: str, problems: list[str]) -> None:
    for key, ok, words in _NUMBER_CHECKS:
        limit = schema.get(key)
        if _is_number(limit) and not ok(value, cast(float, limit)):
            problems.append(f"{where}: must be {words} {limit}")
    step = schema.get("multipleOf")
    if _is_number(step):
        quotient = value / cast(float, step)
        if not math.isclose(quotient, round(quotient), rel_tol=0, abs_tol=1e-9):
            problems.append(f"{where}: must be a multiple of {step}")


def _validate_composition(
    value: JsonValue, schema: Schema, root: Schema, path: str, problems: list[str]
) -> None:
    where = _where(path)
    all_of = schema.get("allOf")
    for sub in all_of if isinstance(all_of, list) else []:
        _validate(value, sub, root, path, problems)
    any_of = schema.get("anyOf")
    if isinstance(any_of, list) and not any(_passes(value, sub, root, path) for sub in any_of):
        problems.append(f"{where}: must match at least one of the anyOf schemas")
    one_of = schema.get("oneOf")
    if isinstance(one_of, list):
        matched = sum(_passes(value, sub, root, path) for sub in one_of)
        if matched != 1:
            problems.append(f"{where}: must match exactly one of the oneOf schemas")
    if "not" in schema and _passes(value, schema["not"], root, path):
        problems.append(f"{where}: must not match the 'not' schema")


def _passes(value: JsonValue, schema: JsonValue | Schema, root: Schema, path: str) -> bool:
    found: list[str] = []
    _validate(value, schema, root, path, found)
    return not found
