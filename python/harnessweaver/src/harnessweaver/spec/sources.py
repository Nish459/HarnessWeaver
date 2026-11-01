"""Finding the profiles a spec ``extends`` (DESIGNS No. 11).

References:

* ``profile://rag`` is a built-in profile shipped with harnessweaver.
  ``profile://acme.baseline@^1`` is a profile contributed by the plugin that
  owns the ``acme`` namespace (resolved by a plugin-aware resolver).
* ``org://acme-baseline@^2`` is an org profile, found on the profile search
  path: ``HARNESSWEAVER_PROFILE_PATH`` (os.pathsep-separated), then
  ``.harness/profiles`` next to the app spec. Files are ``<name>.yaml`` or
  ``<name>@<version>.yaml``. The first directory holding any file for a name owns
  that name, and the highest version there that matches the range wins.
* Anything else is a file path, relative to the document that names it.

A profile can extend other profiles; parents come before the profile itself.

A profile is *app-owned* when the app's team can write it: it's in ``.harness/profiles``
next to the app spec, or it's a file named by the app spec or another app-owned profile.
Everything else belongs to the platform. The loader merges app-owned profiles after the
platform's, so the platform's locks bind them (R1, ADR-0043).
"""

import os
import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, replace
from importlib import resources
from pathlib import Path
from typing import Any, Final, Protocol

from harnessweaver.core.errors import SpecError
from harnessweaver.core.plugins import RESERVED_NAMESPACES
from harnessweaver.core.registry import PluginCatalog
from harnessweaver.core.semver import Version, VersionRange
from harnessweaver.spec._raw import as_map
from harnessweaver.spec.merge import LayerKind
from harnessweaver.spec.yaml import load_yaml, load_yaml_file

__all__ = [
    "PROFILE_PATH_ENV",
    "BuiltinProfiles",
    "PluginProfiles",
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
    app_owned: bool = False  # the app's team can write it, so it merges after the platform's

    @property
    def identity(self) -> str:
        """What makes two profiles the same one: the file, for a profile read from a file.

        The name won't do: two files can be named by the same relative text.
        """
        if self.directory is not None and self.source is not None:
            return str(Path(self.source).resolve())
        return self.layer_name


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

    def __init__(self, directories: Sequence[Path], app_directory: Path | None = None) -> None:
        """Search ``directories`` in order; ``app_directory`` is the one the app's team owns."""
        self.directories = list(directories)
        self.app_directory = app_directory

    @classmethod
    def from_environment(
        cls, app_directory: Path | None, extra: Sequence[Path] = ()
    ) -> "ProfileDirectories":
        """Search ``extra``, then ``HARNESSWEAVER_PROFILE_PATH``, then ``.harness/profiles``."""
        directories = list(extra)
        env = os.environ.get(PROFILE_PATH_ENV, "")
        directories.extend(Path(p) for p in env.split(os.pathsep) if p)
        if app_directory is None:
            return cls(directories)
        app_profiles = app_directory / ".harness" / "profiles"
        return cls([*directories, app_profiles], app_profiles)

    def resolve(self, ref: ProfileRef, relative_to: Path | None) -> ResolvedProfile | None:
        if ref.scheme == "file":
            return self._resolve_file(ref, relative_to)
        if ref.scheme != "org":
            return None
        # The first directory holding the name owns it. Versions are never compared across
        # directories, or a later directory could outrank an earlier one with a higher number.
        for directory in self.directories:
            paths = [
                path
                for path in [
                    directory / f"{ref.name}.yaml",
                    *sorted(directory.glob(f"{ref.name}@*.yaml")),
                ]
                if path.is_file()
            ]
            if paths:
                break
        else:
            return None
        candidates: list[tuple[Version | None, Path, dict[str, Any]]] = []
        for path in paths:
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
        return ResolvedProfile(
            label,
            LayerKind.ORG,
            document,
            str(path),
            path.parent,
            app_owned=directory == self.app_directory,
        )

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


class PluginProfiles:
    """Profiles contributed by plugins: ``profile://<namespace>.<name>[@range]``.

    Only the plugin that owns the namespace is imported (S8). The loader checks
    the namespace against ``plugins.allow`` once the layers are merged.
    """

    def __init__(self, catalog: PluginCatalog) -> None:
        self.catalog = catalog

    def resolve(self, ref: ProfileRef, relative_to: Path | None) -> ResolvedProfile | None:
        if ref.scheme != "profile" or "." not in ref.name:
            return None
        namespace, _, name = ref.name.partition(".")
        if namespace in RESERVED_NAMESPACES:
            return None
        loaded = self.catalog.load(namespace)
        path = loaded.plugin.profiles.get(name)
        if path is None:
            offered = ", ".join(sorted(loaded.plugin.profiles)) or "none"
            raise SpecError(
                f"plugin {namespace!r} has no profile {name!r} (it has: {offered})",
                reference=ref.text,
            )
        resource = loaded.resource(path)
        document = load_yaml(resource.read_text(encoding="utf-8"), f"profile://{ref.name}")
        if not isinstance(document, dict):
            raise SpecError(f"profile://{ref.name} is not a map")
        version = _check_range(ref, document, f"profile://{ref.name}")  # pyright: ignore[reportUnknownArgumentType]
        label = f"profile://{ref.name}@{version}" if version else f"profile://{ref.name}"
        source = f"{loaded.source.module}:{path}"
        return ResolvedProfile(label, LayerKind.ORG, document, source, None)  # pyright: ignore[reportUnknownArgumentType]


def _add_profile(resolved: list[ResolvedProfile], profile: ResolvedProfile) -> None:
    """Add a profile once. A file both the app and the platform name stays the platform's."""
    for index, known in enumerate(resolved):
        if known.identity == profile.identity:
            if known.app_owned and not profile.app_owned:
                resolved[index] = profile
            return
    resolved.append(profile)


def resolve_extends(
    extends: Iterable[str],
    resolvers: Sequence[ProfileResolver],
    relative_to: Path | None,
    _stack: tuple[str, ...] = (),
    _named_by_app: bool = True,
) -> list[ResolvedProfile]:
    """Resolve references (and their own ``extends``), parents first, without duplicates.

    ``extends`` is the app spec's list, so the files it names are app-owned, and so are the
    files an app-owned profile names (ADR-0043).

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
        if ref.scheme == "file" and _named_by_app:
            found = replace(found, app_owned=True)
        if found.identity in _stack:
            chain = " -> ".join((*_stack, found.identity))
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
            (*_stack, found.identity),
            found.app_owned,
        ):
            _add_profile(resolved, parent)
        _add_profile(resolved, found)
    return resolved
