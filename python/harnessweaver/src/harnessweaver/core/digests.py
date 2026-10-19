"""Canonical JSON and digests: the same value gives the same digest in every language.

Tool definitions are pinned by digest (S2), and approvals match calls and outputs
by digest (DESIGNS No. 18), so the canonical form is part of the contract
(fixtures suite ``governor``):

* object keys sorted, no whitespace, non-ASCII characters escaped as ``\\uXXXX``;
* a number with no fractional part is written as an integer (``1.0`` -> ``1``), so
  languages that don't tell integers from floats agree;
* the digest is ``sha256:`` followed by the lowercase hex SHA-256 of that text.
"""

import hashlib
import json

from pydantic import JsonValue

__all__ = ["canonical_digest", "canonical_json"]


def _normalized(value: JsonValue) -> JsonValue:
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, dict):
        return {key: _normalized(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_normalized(item) for item in value]
    return value


def canonical_json(value: JsonValue) -> str:
    """The canonical text of a JSON value.

    Raises:
        ValueError: For NaN or infinity, which JSON can't represent.
    """
    return json.dumps(
        _normalized(value),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    )


def canonical_digest(value: JsonValue) -> str:
    """``sha256:<hex>`` of :func:`canonical_json`."""
    return "sha256:" + hashlib.sha256(canonical_json(value).encode("ascii")).hexdigest()
