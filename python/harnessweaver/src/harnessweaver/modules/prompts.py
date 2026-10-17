"""Versioned prompts, resolved by ``name@version`` and rendered with ``str.format_map`` (ADR-0013).

Prompt files live in ``prompts.dir`` and are named ``<name>@<version>.md`` (or
``.txt``). A reference picks a file:

* ``support_answer@4.1.0`` -> exactly that version;
* ``support_answer@4`` -> the file named ``@4``, or else the highest ``4.x.y``;
* ``support_answer`` -> the highest version, or the unversioned ``support_answer.md``.

There is no template language (R12): ``{question}`` is replaced, ``{{`` is a
literal brace, and a missing variable is an error.
"""

import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

import anyio.to_thread

from harnessweaver.core.errors import SpecError
from harnessweaver.core.semver import Version, VersionRange

__all__ = ["Prompt", "PromptStore"]

_FILE: Final = re.compile(
    r"^(?P<name>[A-Za-z0-9_.-]+?)(?:@(?P<version>[A-Za-z0-9.+-]+))?\.(md|txt)$"
)


@dataclass(frozen=True, slots=True)
class Prompt:
    """One prompt file."""

    name: str
    version: str | None
    path: Path

    @property
    def ref(self) -> str:
        return self.name if self.version is None else f"{self.name}@{self.version}"


class _Variables(dict[str, Any]):
    def __missing__(self, key: str) -> Any:
        raise KeyError(key)


class PromptStore:
    """Prompts from one directory. Files are listed once and read on first use."""

    def __init__(self, directory: Path) -> None:
        self._directory = directory
        self._index: dict[str, list[Prompt]] | None = None
        self._texts: dict[Path, str] = {}

    @property
    def directory(self) -> Path:
        return self._directory

    def _prompts(self) -> dict[str, list[Prompt]]:
        if self._index is None:
            index: dict[str, list[Prompt]] = {}
            if self._directory.is_dir():
                for path in sorted(self._directory.iterdir()):
                    match = _FILE.match(path.name)
                    if match and path.is_file():
                        prompt = Prompt(match["name"], match["version"], path)
                        index.setdefault(prompt.name, []).append(prompt)
            self._index = index
        return self._index

    def find(self, ref: str) -> Prompt:
        """The prompt file for ``ref``.

        Raises:
            SpecError: If no file matches.
        """
        name, _, wanted = ref.partition("@")
        candidates = self._prompts().get(name, [])
        exact = [p for p in candidates if p.version == (wanted or None)]
        if exact:
            return exact[0]
        versioned: dict[Version, Prompt] = {}
        for prompt in candidates:
            try:
                versioned[Version.parse(prompt.version or "")] = prompt
            except ValueError:
                continue
        try:
            accepted = VersionRange.parse(wanted) if wanted else VersionRange.parse("*")
        except ValueError:
            accepted = None
        best = accepted.max_satisfying(list(versioned)) if accepted is not None else None
        if best is None:
            raise SpecError(f"no prompt {ref!r} in {self._directory}", prompt=ref)
        return versioned[best]

    async def text(self, ref: str) -> str:
        prompt = self.find(ref)
        if prompt.path not in self._texts:
            self._texts[prompt.path] = await anyio.to_thread.run_sync(
                lambda: prompt.path.read_text(encoding="utf-8")
            )
        return self._texts[prompt.path]

    async def render(self, ref: str, variables: Mapping[str, Any]) -> str:
        """Fill in ``{name}`` placeholders.

        Raises:
            SpecError: If the prompt doesn't exist or uses a variable that wasn't given.
        """
        template = await self.text(ref)
        try:
            return template.format_map(_Variables(variables))
        except KeyError as exc:
            raise SpecError(
                f"prompt {ref!r} uses {{{exc.args[0]}}}, which wasn't given", prompt=ref
            ) from None
        except (ValueError, IndexError, AttributeError) as exc:
            raise SpecError(f"prompt {ref!r} has a malformed placeholder: {exc}") from None
