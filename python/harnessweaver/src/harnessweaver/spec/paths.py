"""Paths into a spec, as written in locks, bounds and ``spec explain``.

A path is dotted keys, with ``[id]`` selecting an item of a keyed list:
``guardrails.input[base-pii].action``. Ids may contain dots (``pii.regex#1``).
A ``*`` segment matches any map key, and ``[*]`` matches any item.
"""

from dataclasses import dataclass

__all__ = ["Item", "Segment", "SpecPath", "format_path", "is_prefix", "matches", "parse_path"]


@dataclass(frozen=True, slots=True)
class Item:
    """A keyed-list item, selected by its ``id``."""

    id: str


type Segment = str | Item
type SpecPath = tuple[Segment, ...]


def parse_path(text: str) -> SpecPath:
    """Parse ``a.b[id].c`` into segments.

    Raises:
        ValueError: If the path is malformed.
    """
    segments: list[Segment] = []
    position = 0
    expect_key = True
    while position < len(text):
        if expect_key:
            end = position
            while end < len(text) and text[end] not in ".[]":
                end += 1
            key = text[position:end].strip()
            if not key:
                raise ValueError(f"invalid spec path {text!r}: empty key")
            segments.append(key)
            position = end
            expect_key = False
        elif text[position] == "[":
            close = text.find("]", position)
            if close == -1 or close == position + 1:
                raise ValueError(f"invalid spec path {text!r}: bad item selector")
            segments.append(Item(text[position + 1 : close]))
            position = close + 1
        elif text[position] == ".":
            position += 1
            expect_key = True
        else:
            raise ValueError(f"invalid spec path {text!r}")
    if expect_key:
        raise ValueError(f"invalid spec path {text!r}: it can't be empty or end with '.'")
    return tuple(segments)


def format_path(path: SpecPath) -> str:
    """Format segments as ``a.b[id].c``."""
    text = ""
    for segment in path:
        if isinstance(segment, Item):
            text += f"[{segment.id}]"
        else:
            text += f".{segment}" if text else segment
    return text


def is_prefix(prefix: SpecPath, path: SpecPath) -> bool:
    """Whether ``prefix`` is ``path`` or an ancestor of it, with ``*`` and ``[*]`` as wildcards."""
    return len(prefix) <= len(path) and matches(prefix, path[: len(prefix)])


def matches(pattern: SpecPath, path: SpecPath) -> bool:
    """Whether ``path`` matches ``pattern``, where ``*`` and ``[*]`` match one segment."""
    if len(pattern) != len(path):
        return False
    for want, have in zip(pattern, path, strict=True):
        if isinstance(want, Item):
            if not isinstance(have, Item) or (want.id != "*" and want.id != have.id):
                return False
        elif isinstance(have, Item) or (want != "*" and want != have):
            return False
    return True
