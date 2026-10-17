"""Tokenizer for cel-lite."""

import re
from dataclasses import dataclass
from enum import StrEnum
from typing import Final

from harnessweaver.core.errors import ExpressionSyntaxError

__all__ = ["Token", "TokenKind", "tokenize"]


class TokenKind(StrEnum):
    INT = "int"
    DOUBLE = "double"
    STRING = "string"
    IDENT = "ident"
    OP = "op"
    EOF = "eof"


@dataclass(frozen=True, slots=True)
class Token:
    kind: TokenKind
    text: str
    pos: int
    value: int | float | str | None = None


_OPERATORS: Final = ("==", "!=", "<=", ">=", "&&", "||", "<", ">", "+", "-", "*", "/", "%", "!",
                     "?", ":", ".", ",", "(", ")", "[", "]", "{", "}")  # fmt: skip
_NUMBER: Final = re.compile(r"0[xX][0-9a-fA-F]+|\d+\.\d+(?:[eE][+-]?\d+)?|\d+[eE][+-]?\d+|\d+")
_IDENT: Final = re.compile(r"[_a-zA-Z][_a-zA-Z0-9]*")
_SIMPLE_ESCAPES: Final = {
    "\\": "\\", "'": "'", '"': '"', "`": "`", "?": "?",
    "a": "\a", "b": "\b", "f": "\f", "n": "\n", "r": "\r", "t": "\t", "v": "\v",
}  # fmt: skip
_HEX_ESCAPES: Final = {"x": 2, "u": 4, "U": 8}


def _error(source: str, pos: int, message: str) -> ExpressionSyntaxError:
    return ExpressionSyntaxError(f"{message} at position {pos}", expression=source, position=pos)


def _read_string(source: str, start: int) -> tuple[str, int]:
    """Read a string literal starting at ``start``; return its value and the end index."""
    pos = start
    raw = source[pos] in "rR"
    if raw:
        pos += 1
    quote = source[pos]
    if source.startswith(quote * 3, pos):
        raise _error(source, start, "triple-quoted strings are not supported")
    pos += 1
    chars: list[str] = []
    while True:
        if pos >= len(source) or source[pos] == "\n":
            raise _error(source, start, "unterminated string")
        char = source[pos]
        if char == quote:
            return "".join(chars), pos + 1
        if char == "\\" and not raw:
            if pos + 1 >= len(source):
                raise _error(source, start, "unterminated string")
            esc = source[pos + 1]
            if esc in _SIMPLE_ESCAPES:
                chars.append(_SIMPLE_ESCAPES[esc])
                pos += 2
                continue
            if esc in _HEX_ESCAPES:
                width = _HEX_ESCAPES[esc]
                digits = source[pos + 2 : pos + 2 + width]
                if len(digits) != width or not all(c in "0123456789abcdefABCDEF" for c in digits):
                    raise _error(source, pos, f"invalid \\{esc} escape")
                code = int(digits, 16)
                if code > 0x10FFFF or 0xD800 <= code <= 0xDFFF:
                    raise _error(source, pos, "escape is not a valid code point")
                chars.append(chr(code))
                pos += 2 + width
                continue
            raise _error(source, pos, f"invalid escape \\{esc}")
        chars.append(char)
        pos += 1


def tokenize(source: str) -> list[Token]:
    """Split ``source`` into tokens, ending with an EOF token.

    Raises:
        ExpressionSyntaxError: On characters or literals cel-lite doesn't accept.
    """
    tokens: list[Token] = []
    pos = 0
    length = len(source)
    while pos < length:
        char = source[pos]
        if char in " \t\r\n":
            pos += 1
            continue
        if source.startswith("//", pos):
            newline = source.find("\n", pos)
            pos = length if newline == -1 else newline + 1
            continue
        if char in "'\"" or (char in "rR" and pos + 1 < length and source[pos + 1] in "'\""):
            value, end = _read_string(source, pos)
            tokens.append(Token(TokenKind.STRING, source[pos:end], pos, value))
            pos = end
            continue
        if char.isdigit():
            match = _NUMBER.match(source, pos)
            assert match is not None
            text = match.group(0)
            end = match.end()
            if end < length and (source[end].isalnum() or source[end] in "_."):
                raise _error(source, pos, f"invalid number {source[pos : end + 1]!r}")
            if text[:2] in {"0x", "0X"}:
                tokens.append(Token(TokenKind.INT, text, pos, int(text, 16)))
            elif any(c in text for c in ".eE"):
                tokens.append(Token(TokenKind.DOUBLE, text, pos, float(text)))
            else:
                tokens.append(Token(TokenKind.INT, text, pos, int(text)))
            pos = end
            continue
        match = _IDENT.match(source, pos)
        if match is not None:
            tokens.append(Token(TokenKind.IDENT, match.group(0), pos))
            pos = match.end()
            continue
        for op in _OPERATORS:
            if source.startswith(op, pos):
                tokens.append(Token(TokenKind.OP, op, pos))
                pos += len(op)
                break
        else:
            raise _error(source, pos, f"unexpected character {char!r}")
    tokens.append(Token(TokenKind.EOF, "", length))
    return tokens
