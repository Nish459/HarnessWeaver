"""Typed views of parsed YAML/JSON data, so spec code stays strictly typed (RULES C1)."""

from typing import Any, cast

__all__ = ["as_list", "as_map"]


def as_map(value: object) -> dict[Any, Any] | None:
    """``value`` as a dict, or ``None`` if it isn't one."""
    return cast("dict[Any, Any]", value) if isinstance(value, dict) else None


def as_list(value: object) -> list[Any] | None:
    """``value`` as a list, or ``None`` if it isn't one."""
    return cast("list[Any]", value) if isinstance(value, list) else None
