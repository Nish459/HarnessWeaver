"""Finding the profiles a spec ``extends`` (DESIGNS No. 11).

References:

* ``profile://rag`` is a built-in profile shipped with harnessweaver.
  ``profile://acme.baseline@^1`` is a profile contributed by the plugin that
  owns the ``acme`` namespace (resolved by a plugin-aware resolver).
* ``org://acme-baseline@^2`` is an org profile, found on the profile search
  path: ``HARNESSWEAVER_PROFILE_PATH`` (os.pathsep-separated), then
  ``.harness/profiles`` next to the app spec. Files are ``<name>.yaml`` or
  ``<name>@<version>.yaml``; the highest version that matches the range wins.
* Anything else is a file path, relative to the document that names it.

A profile can extend other profiles; parents come before the profile itself.
"""

import os
import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from importlib import resources
from pathlib import Path
from typing import Any, Final, Protocol

from harnessweaver.core.errors import SpecError
from harnessweaver.core.semver import Version, VersionRange
from harnessweaver.spec._raw import as_map
from harnessweaver.spec.merge import LayerKind
from harnessweaver.spec.yaml import load_yaml, load_yaml_file

__all__ = [
    "PROFILE_PATH_ENV",
    "BuiltinProfiles",
    "ProfileDirectories",
    "ProfileRef",
    "ProfileResolver",
    "ResolvedProfile",
    "parse_ref",
    "resolve_extends",
]

PROFILE_PATH_ENV: Final = "HARNESSWEAVER_PROFILE_PATH"
_REF: Final = re.compile(
    r"^(?P<scheme>profile|org)://(?P<name>[A-Za-z0-9._-]+)(?:@(?P<range>.+))?$"
)


@dataclass(frozen=True, slots=True)
class ProfileRef:
    """A parsed ``extends`` entry."""

    text: str
    scheme: str  # "profile", "org" or "file"
    name: str
    range: VersionRange | None


def parse_ref(text: str) -> ProfileRef:
    """Parse ``profile://name[@range]``, ``org://name[@range]`` or a file path.

    Raises:
        SpecError: If the version range is malformed.
    """
    match = _REF.match(text.strip())
    if match is None:
        return ProfileRef(text, "file", text.strip(), None)
    version_range = None
    if match["range"]:
        try:
            version_range = VersionRange.parse(match["range"])
        except ValueError as exc:
            raise SpecError(f"extends {text!r}: {exc}") from None
    return ProfileRef(text, match["scheme"], match["name"], version_range)


@dataclass(frozen=True, slots=True)
class ResolvedProfile:
    """A profile document found for a reference."""

    layer_name: str  # e.g. "org://acme-baseline@2.3.0"
    kind: LayerKind
    document: dict[str, Any]
    source: str | None
    directory: Path | None  # where its own relative references resolve from


class ProfileResolver(Protocol):
    """Finds profiles. Return ``None`` to let the next resolver try."""

    def resolve(self, ref: ProfileRef, relative_to: Path | None) -> ResolvedProfile | None: ...


def _version_of(document: dict[str, Any]) -> Version | None:
    metadata = as_map(document.get("metadata"))
    text = metadata.get("version") if metadata is not None else None
    if not isinstance(text, str):
        return None
    try:
        return Version.parse(text)
    except ValueError:
        return None


def _check_range(ref: ProfileRef, document: dict[str, Any], where: str) -> Version | None:
    version = _version_of(document)
    if ref.range is not None and (version is None or not ref.range.contains(version)):
        found = "no version" if version is None else f"version {version}"
        raise SpecError(f"extends {ref.text!r}: {where} has {found}, outside {ref.range}")
    return version


class BuiltinProfiles:
    """The profiles shipped inside the harnessweaver package (``profile://<name>``)."""

    def resolve(self, ref: ProfileRef, relative_to: Path | None) -> ResolvedProfile | None:
        if ref.scheme != "profile" or "." in ref.name:
            return None
        resource = resources.files("harnessweaver.profiles").joinpath(f"{ref.name}.yaml")
        if not resource.is_file():
            return None
        document = load_yaml(resource.read_text(encoding="utf-8"), f"profile://{ref.name}")
        if not isinstance(document, dict):
            raise SpecError(f"built-in profile {ref.name!r} is not a map")
        _check_range(ref, document, f"profile://{ref.name}")  # pyright: ignore[reportUnknownArgumentType]
        kind = LayerKind.DEFAULTS if ref.name == "defaults" else LayerKind.PROFILE
        return ResolvedProfile(f"profile://{ref.name}", kind, document, None, None)  # pyright: ignore[reportUnknownArgumentType]


class ProfileDirectories:
    """Org profiles (``org://name@range``) and files, from search directories."""

    def __init__(self, directories: Sequence[Path]) -> None:
        self.directories = list(directories)

    @classmethod
    def from_environment(
        cls, app_directory: Path | None, extra: Sequence[Path] = ()
    ) -> "ProfileDirectories":
        """Search ``extra``, then ``HARNESSWEAVER_PROFILE_PATH``, then ``.harness/profiles``."""
        directories = list(extra)
        env = os.environ.get(PROFILE_PATH_ENV, "")
        directories.extend(Path(p) for p in env.split(os.pathsep) if p)
        if app_directory is not None:
            directories.append(app_directory / ".harness" / "profiles")
        return cls(directories)

    def resolve(self, ref: ProfileRef, relative_to: Path | None) -> ResolvedProfile | None:
        if ref.scheme == "file":
            return self._resolve_file(ref, relative_to)
        if ref.scheme != "org":
            return None
        candidates: list[tuple[Version | None, Path, dict[str, Any]]] = []
        for directory in self.directories:
            for path in [
                directory / f"{ref.name}.yaml",
                *sorted(directory.glob(f"{ref.name}@*.yaml")),
            ]:
                if not path.is_file():
                    continue
                document = load_yaml_file(path)
                if not isinstance(document, dict):
                    raise SpecError(f"{path} is not a map")
                version = _version_of(document)  # pyright: ignore[reportUnknownArgumentType]
                if ref.range is None or (version is not None and ref.range.contains(version)):
                    candidates.append((version, path, document))  # pyright: ignore[reportUnknownArgumentType]
        if not candidates:
            return None
        version, path, document = max(
            candidates, key=lambda c: (c[0] is not None, c[0] or Version(0, 0, 0))
        )
        label = f"org://{ref.name}@{version}" if version else f"org://{ref.name}"
        return ResolvedProfile(label, LayerKind.ORG, document, str(path), path.parent)

    def _resolve_file(self, ref: ProfileRef, relative_to: Path | None) -> ResolvedProfile | None:
        path = Path(ref.name)
        if not path.is_absolute() and relative_to is not None:
            path = relative_to / path
        if not path.is_file():
            return None
        document = load_yaml_file(path)
        if not isinstance(document, dict):
            raise SpecError(f"{path} is not a map")
        return ResolvedProfile(str(ref.name), LayerKind.ORG, document, str(path), path.parent)  # pyright: ignore[reportUnknownArgumentType]


def resolve_extends(
    extends: Iterable[str],
    resolvers: Sequence[ProfileResolver],
    relative_to: Path | None,
    _stack: tuple[str, ...] = (),
) -> list[ResolvedProfile]:
    """Resolve references (and their own ``extends``), parents first, without duplicates.

    Raises:
        UnknownProvider: (as SpecError) if a reference can't be found.
        SpecError: On cycles or malformed profile documents.
    """
    resolved: list[ResolvedProfile] = []
    for text in extends:
        ref = parse_ref(text)
        found = next((r for r in (res.resolve(ref, relative_to) for res in resolvers) if r), None)
        if found is None:
            raise SpecError(f"can't find profile {text!r}; see {PROFILE_PATH_ENV}", reference=text)
        if found.layer_name in _stack:
            chain = " -> ".join((*_stack, found.layer_name))
            raise SpecError(f"profiles extend each other in a cycle: {chain}")
        if found.document.get("kind") != "Profile":
            raise SpecError(f"{found.layer_name} must be a document of kind Profile")
        parents: Any = found.document.get("extends", [])
        if isinstance(parents, str):
            parents = [parents]
        if not isinstance(parents, list):
            raise SpecError(f"extends in {found.layer_name} must be a list")
        for parent in resolve_extends(
            [str(p) for p in parents],  # pyright: ignore[reportUnknownVariableType, reportUnknownArgumentType]
            resolvers,
            found.directory or relative_to,
            (*_stack, found.layer_name),
        ):
            if all(parent.layer_name != r.layer_name for r in resolved):
                resolved.append(parent)
        if all(found.layer_name != r.layer_name for r in resolved):
            resolved.append(found)
    return resolved
