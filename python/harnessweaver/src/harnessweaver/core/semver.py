"""Semantic versions and version ranges.

Used for profile references (``org://acme-baseline@^2``) and for the contract
ranges plugins declare (``contract=">=1.0,<2"``). The range syntax follows
npm's, which is part of the contract (fixtures suite ``semver``):

* Comparators: ``1.2.3``, ``=1.2.3``, ``>1.2``, ``>=1.2``, ``<2``, ``<=1.4``.
* Caret ``^1.2.3`` allows changes that keep the left-most non-zero part.
* Tilde ``~1.2.3`` allows patch-level changes.
* Partial versions and wildcards (``1``, ``1.2``, ``1.x``, ``*``) cover the
  versions they leave open.
* Comparators in a set are joined by commas or spaces (all must match), and
  sets are joined by ``||`` (any may match).
* A prerelease version such as ``2.0.0-rc.1`` only matches a set that has a
  comparator with a prerelease on the same ``major.minor.patch``.
"""

import re
from dataclasses import dataclass
from functools import total_ordering
from typing import Final, Literal, Self

__all__ = ["Version", "VersionRange"]

_NUMBER: Final = r"0|[1-9]\d*"
_IDENT: Final = r"[0-9A-Za-z-]+"
_VERSION: Final = re.compile(
    rf"^(?P<major>{_NUMBER})\.(?P<minor>{_NUMBER})\.(?P<patch>{_NUMBER})"
    rf"(?:-(?P<pre>{_IDENT}(?:\.{_IDENT})*))?(?:\+(?P<build>{_IDENT}(?:\.{_IDENT})*))?$"
)
_PARTIAL: Final = re.compile(
    rf"^(?P<major>{_NUMBER}|[xX*])(?:\.(?P<minor>{_NUMBER}|[xX*]))?(?:\.(?P<patch>{_NUMBER}|[xX*]))?"
    rf"(?:-(?P<pre>{_IDENT}(?:\.{_IDENT})*))?(?:\+{_IDENT}(?:\.{_IDENT})*)?$"
)
_COMPARATOR: Final = re.compile(r"^(?P<op>\^|~|>=|<=|>|<|=)?\s*(?P<version>\S+)$")

type _Identifier = int | str
type _Op = Literal[">=", ">", "<", "<=", "="]


def _parse_prerelease(text: str | None) -> tuple[_Identifier, ...]:
    if not text:
        return ()
    identifiers: list[_Identifier] = []
    for part in text.split("."):
        if part.isdigit():
            if len(part) > 1 and part.startswith("0"):
                raise ValueError(f"numeric prerelease identifier {part!r} has a leading zero")
            identifiers.append(int(part))
        else:
            identifiers.append(part)
    return tuple(identifiers)


def _identifier_key(identifier: _Identifier) -> tuple[int, int, str]:
    # Numeric identifiers sort before alphanumeric ones (SemVer 2.0.0 No. 11).
    if isinstance(identifier, int):
        return (0, identifier, "")
    return (1, 0, identifier)


@total_ordering
@dataclass(frozen=True, slots=True)
class Version:
    """A SemVer 2.0.0 version. Build metadata is accepted and ignored."""

    major: int
    minor: int
    patch: int
    prerelease: tuple[_Identifier, ...] = ()

    @classmethod
    def parse(cls, text: str) -> Self:
        """Parse ``MAJOR.MINOR.PATCH[-PRERELEASE][+BUILD]``.

        Raises:
            ValueError: If the text is not a valid version.
        """
        match = _VERSION.match(text.strip())
        if match is None:
            raise ValueError(f"invalid version {text!r}")
        return cls(
            int(match["major"]),
            int(match["minor"]),
            int(match["patch"]),
            _parse_prerelease(match["pre"]),
        )

    @property
    def release(self) -> tuple[int, int, int]:
        """The ``(major, minor, patch)`` part."""
        return (self.major, self.minor, self.patch)

    def _key(self) -> tuple[int, int, int, int, tuple[tuple[int, int, str], ...]]:
        # A release sorts after all of its prereleases.
        has_release = 0 if self.prerelease else 1
        pre = tuple(_identifier_key(i) for i in self.prerelease)
        return (self.major, self.minor, self.patch, has_release, pre)

    def __lt__(self, other: object) -> bool:
        if not isinstance(other, Version):
            return NotImplemented
        return self._key() < other._key()

    def __str__(self) -> str:
        text = f"{self.major}.{self.minor}.{self.patch}"
        if self.prerelease:
            text += "-" + ".".join(str(i) for i in self.prerelease)
        return text


@dataclass(frozen=True, slots=True)
class _Comparator:
    op: _Op
    version: Version

    def test(self, version: Version) -> bool:
        match self.op:
            case ">=":
                return version >= self.version
            case ">":
                return version > self.version
            case "<":
                return version < self.version
            case "<=":
                return version <= self.version
            case "=":
                return version == self.version


@dataclass(frozen=True, slots=True)
class _Partial:
    major: int | None
    minor: int | None
    patch: int | None
    prerelease: tuple[_Identifier, ...]

    def floor(self) -> Version:
        return Version(self.major or 0, self.minor or 0, self.patch or 0, self.prerelease)


def _parse_partial(text: str) -> _Partial:
    match = _PARTIAL.match(text)
    if match is None:
        raise ValueError(f"invalid version {text!r} in range")

    def number(name: str) -> int | None:
        value = match[name]
        return None if value is None or value in {"x", "X", "*"} else int(value)

    major, minor, patch = number("major"), number("minor"), number("patch")
    if (major is None and minor is not None) or (minor is None and patch is not None):
        raise ValueError(f"invalid version {text!r} in range; a wildcard can't precede a number")
    prerelease = _parse_prerelease(match["pre"])
    if prerelease and patch is None:
        raise ValueError(f"invalid version {text!r} in range; a prerelease needs a full version")
    return _Partial(major, minor, patch, prerelease)


def _caret(p: _Partial) -> list[_Comparator]:
    if p.major is None:
        return []
    low = _Comparator(">=", p.floor())
    if p.major > 0 or p.minor is None:
        high = Version(p.major + 1, 0, 0)
    elif p.minor > 0 or p.patch is None:
        high = Version(0, p.minor + 1, 0)
    else:
        high = Version(0, 0, p.patch + 1)
    return [low, _Comparator("<", high)]


def _tilde(p: _Partial) -> list[_Comparator]:
    if p.major is None:
        return []
    low = _Comparator(">=", p.floor())
    if p.minor is None:
        return [low, _Comparator("<", Version(p.major + 1, 0, 0))]
    return [low, _Comparator("<", Version(p.major, p.minor + 1, 0))]


def _next_open(p: _Partial) -> Version:
    """The first version after everything a partial version covers."""
    assert p.major is not None
    if p.minor is None:
        return Version(p.major + 1, 0, 0)
    return Version(p.major, p.minor + 1, 0)


def _desugar(op: str, p: _Partial) -> list[_Comparator]:
    if op == "^":
        return _caret(p)
    if op == "~":
        return _tilde(p)
    if p.major is None:  # "*", ">=*", ...
        return [] if op in {"", "=", ">=", "<="} else [_Comparator("<", Version(0, 0, 0))]
    full = p.patch is not None
    if op in {"", "="}:
        if full:
            return [_Comparator("=", p.floor())]
        return [_Comparator(">=", p.floor()), _Comparator("<", _next_open(p))]
    if op == ">=":
        return [_Comparator(">=", p.floor())]
    if op == ">":
        return [_Comparator(">", p.floor())] if full else [_Comparator(">=", _next_open(p))]
    if op == "<":
        return [_Comparator("<", p.floor())]
    # "<="
    return [_Comparator("<=", p.floor())] if full else [_Comparator("<", _next_open(p))]


def _satisfies(comparators: tuple[_Comparator, ...], version: Version) -> bool:
    if not all(c.test(version) for c in comparators):
        return False
    if not version.prerelease:
        return True
    return any(c.version.prerelease and c.version.release == version.release for c in comparators)


@dataclass(frozen=True, slots=True)
class VersionRange:
    """A set of versions, written in npm range syntax (see the module docstring)."""

    text: str
    _sets: tuple[tuple[_Comparator, ...], ...]

    @classmethod
    def parse(cls, text: str) -> Self:
        """Parse a range such as ``^1.2``, ``>=1.0,<2`` or ``~1.4 || ^2``.

        Raises:
            ValueError: If the range is malformed.
        """
        sets: list[tuple[_Comparator, ...]] = []
        for alternative in text.split("||"):
            alternative = alternative.strip()
            comparators: list[_Comparator] = []
            if alternative:
                tokens = [t for t in re.split(r"[,\s]+", alternative) if t]
                # Allow a space between an operator and its version: ">= 1.2".
                merged: list[str] = []
                for token in tokens:
                    if merged and merged[-1] in {"^", "~", ">=", "<=", ">", "<", "="}:
                        merged[-1] += token
                    else:
                        merged.append(token)
                for token in merged:
                    match = _COMPARATOR.match(token)
                    if match is None or match["version"][0] in "^~<>=":
                        raise ValueError(f"invalid comparator {token!r} in range {text!r}")
                    comparators.extend(
                        _desugar(match["op"] or "", _parse_partial(match["version"]))
                    )
            elif "||" in text:
                raise ValueError(f"empty alternative in range {text!r}")
            sets.append(tuple(comparators))
        return cls(text.strip(), tuple(sets))

    def contains(self, version: Version | str) -> bool:
        """Return whether ``version`` is in the range."""
        if isinstance(version, str):
            version = Version.parse(version)
        return any(_satisfies(comparators, version) for comparators in self._sets)

    def __contains__(self, version: object) -> bool:
        return isinstance(version, Version | str) and self.contains(version)

    def max_satisfying(self, versions: list[Version]) -> Version | None:
        """Return the highest version in ``versions`` that the range contains."""
        matching = [v for v in versions if self.contains(v)]
        return max(matching) if matching else None

    def __str__(self) -> str:
        return self.text
