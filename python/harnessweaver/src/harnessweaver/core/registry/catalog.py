"""Plugin discovery: the installed plugins, known from entry-point metadata (S8)."""

import functools
import importlib
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from importlib import resources
from importlib.metadata import entry_points
from importlib.resources.abc import Traversable
from typing import Literal, Self

from harnessweaver.core.errors import (
    PluginConflict,
    SpecError,
    UnknownProvider,
)
from harnessweaver.core.plugins import (
    BUILTIN_NAMESPACE,
    ENTRY_POINT_GROUP,
    RESERVED_NAMESPACES,
    Plugin,
    as_plugin,
)

__all__ = ["LoadedPlugin", "PluginCatalog", "PluginSource", "import_target"]


@dataclass(frozen=True, slots=True)
class PluginSource:
    """Where a plugin can be imported from, known without importing it."""

    namespace: str
    target: str
    """``module`` (attribute ``plugin``) or ``module:attribute``."""
    origin: Literal["entry_point", "local", "builtin"]
    distribution: str | None = None

    @property
    def module(self) -> str:
        return self.target.partition(":")[0]


@dataclass(frozen=True, slots=True)
class LoadedPlugin:
    """An imported plugin and where it came from."""

    plugin: Plugin
    source: PluginSource

    def resource(self, path: str) -> Traversable:
        """A file shipped with the plugin, such as a profile, relative to its module."""
        return resources.files(self.source.module).joinpath(path)


def import_target(target: str) -> object:
    """Import ``module`` (attribute ``plugin``) or ``module:attribute``."""
    module_name, _, attribute = target.partition(":")
    value: object = importlib.import_module(module_name)
    for part in (attribute or "plugin").split("."):
        value = getattr(value, part)
    return value


_BUILTIN_SOURCE = PluginSource(BUILTIN_NAMESPACE, "harnessweaver.builtins:plugin", "builtin")


class PluginCatalog:
    """The plugins installed in this environment, from entry-point metadata.

    The process-wide catalog (:meth:`default`) is read-only after discovery
    (C4); it only memoizes plugins it has imported.
    """

    def __init__(
        self,
        sources: Iterable[PluginSource] = (),
        *,
        importer: Callable[[str], object] = import_target,
    ) -> None:
        self._sources: dict[str, list[PluginSource]] = {}
        for source in sources:
            self._sources.setdefault(source.namespace, []).append(source)
        self._importer = importer
        self._loaded: dict[str, LoadedPlugin] = {}

    @classmethod
    def discover(cls) -> Self:
        """Read the ``harnessweaver.plugins`` entry points. Imports nothing (S8)."""
        found = [
            PluginSource(
                ep.name,
                ep.value,
                "entry_point",
                ep.dist.name if ep.dist is not None else None,
            )
            for ep in entry_points(group=ENTRY_POINT_GROUP)
        ]
        return cls(found)

    @staticmethod
    def default() -> "PluginCatalog":
        """The catalog of this process's installed plugins, discovered once."""
        return _default_catalog()

    def sources(self) -> Mapping[str, tuple[PluginSource, ...]]:
        """Installed plugin sources by namespace."""
        return {ns: tuple(found) for ns, found in sorted(self._sources.items())}

    def problems(self) -> list[str]:
        """Installation problems ``doctor`` should report: shared or reserved namespaces."""
        found: list[str] = []
        for namespace, sources in sorted(self._sources.items()):
            if namespace in RESERVED_NAMESPACES:
                found.append(f"namespace {namespace!r} is reserved for the built-in plugin")
            if len(sources) > 1:
                where = ", ".join(s.distribution or s.target for s in sources)
                found.append(f"namespace {namespace!r} is claimed by several plugins: {where}")
        return found

    def _import(self, source: PluginSource) -> LoadedPlugin:
        # The built-in plugin always comes from the core itself, never a stand-in.
        importer = import_target if source.origin == "builtin" else self._importer
        try:
            value = importer(source.target)
        except (ImportError, AttributeError) as exc:
            raise SpecError(
                f"can't import plugin {source.namespace!r} from {source.target!r}: "
                f"{type(exc).__name__}",
                plugin=source.namespace,
            ) from exc
        plugin = as_plugin(value, f"plugin {source.namespace!r} ({source.target})")
        return LoadedPlugin(plugin, source)

    def load(self, namespace: str) -> LoadedPlugin:
        """Import the plugin that owns ``namespace``.

        Raises:
            UnknownProvider: If no installed plugin claims it.
            PluginConflict: If several do, or the plugin declares another namespace.
        """
        if namespace in self._loaded:
            return self._loaded[namespace]
        if namespace == BUILTIN_NAMESPACE or namespace in RESERVED_NAMESPACES:
            loaded = self._import(_BUILTIN_SOURCE)
        else:
            sources = self._sources.get(namespace, [])
            if not sources:
                raise UnknownProvider(
                    f"no installed plugin provides namespace {namespace!r}; install one "
                    f"that does, or list an in-repo module under plugins.local",
                    namespace=namespace,
                )
            if len(sources) > 1:
                where = ", ".join(s.distribution or s.target for s in sources)
                raise PluginConflict(
                    f"namespace {namespace!r} is claimed by several plugins: {where}",
                    namespace=namespace,
                )
            loaded = self._import(sources[0])
            if loaded.plugin.namespace != namespace:
                raise PluginConflict(
                    f"entry point {namespace!r} exposes a plugin with namespace "
                    f"{loaded.plugin.namespace!r}; they must match",
                    namespace=namespace,
                )
        self._loaded[namespace] = loaded
        return loaded

    def load_local(self, target: str) -> LoadedPlugin:
        """Import an in-repo plugin listed under ``plugins.local``.

        Raises:
            SpecError: If it can't be imported or isn't a ``Plugin``.
            PluginConflict: If its namespace is reserved or already installed.
        """
        loaded = self._import(PluginSource("(local)", target, "local"))
        namespace = loaded.plugin.namespace
        if namespace in RESERVED_NAMESPACES:
            raise PluginConflict(
                f"local plugin {target!r} uses the reserved namespace {namespace!r}",
                namespace=namespace,
            )
        if namespace in self._sources:
            raise PluginConflict(
                f"local plugin {target!r} uses namespace {namespace!r}, which an installed "
                f"plugin already claims",
                namespace=namespace,
            )
        return LoadedPlugin(loaded.plugin, PluginSource(namespace, target, "local"))


@functools.cache
def _default_catalog() -> PluginCatalog:
    return PluginCatalog.discover()
