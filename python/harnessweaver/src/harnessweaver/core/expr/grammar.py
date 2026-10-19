"""cel-lite's limits, functions, methods, macros and reserved words."""

from typing import Final

__all__ = [
    "GLOBAL_FUNCTIONS",
    "MACROS",
    "MAX_DEPTH",
    "MAX_LENGTH",
    "METHODS",
    "RELATIONS",
    "RESERVED",
]

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

RELATIONS: Final = frozenset({"==", "!=", "<", "<=", ">", ">="})
RESERVED: Final = frozenset(
    {
        "as", "break", "const", "continue", "else", "for", "function", "if", "import", "let",
        "loop", "package", "namespace", "return", "var", "void", "while",
    }
)  # fmt: skip
