"""Plugin discovery (:class:`PluginCatalog`) and per-harness registration (:class:`Registry`).

The loading lifecycle (DESIGNS No. 13):

1. **Discover** entry-point metadata. Nothing is imported.
2. **Resolve** the namespaces a spec references. A name's namespace is the text
   before its first dot; reserved namespaces belong to the built-in plugin.
3. **Allow**: a namespace outside the org's ``plugins.allow`` fails (S8).
4. **Import** only the referenced plugins, and check their contract range (V5).
5. **Register** their contributions in this harness's registry (C4).

Every failure is a :class:`~harnessweaver.errors.SpecError` subclass raised at
load time, never at run time (R4).
"""

import functools
import importlib
from collections.abc import Callable, Collection, Iterable, Mapping
from dataclasses import dataclass
from importlib import resources
from importlib.metadata import entry_points
from importlib.resources.abc import Traversable
from typing import Literal, Self

from harnessweaver.core.errors import (
    IncompatibleContract,
    PluginConflict,
    PluginNotAllowed,
    SpecError,
    UnknownProvider,
)
from harnessweaver.core.middleware import MiddlewareDef
from harnessweaver.core.plugins import (
    BUILTIN_NAMESPACE,
    CONTRACT_VERSION,
    ENTRY_POINT_GROUP,
    RESERVED_NAMESPACES,
    AdapterInfo,
    Contribution,
    Plugin,
    ProviderInfo,
    RunnerInfo,
    as_plugin,
    check_owned,
    namespace_of,
)

__all__ = [
    "LoadedPlugin",
    "PluginCatalog",
    "PluginSource",
    "Registry",
    "is_allowed",
    "owner_of",
]


def owner_of(name: str) -> str:
    """The namespace of the plugin that owns ``name`` (fixtures suite ``plugins``)."""
    space = namespace_of(name)
    return BUILTIN_NAMESPACE if space in RESERVED_NAMESPACES else space


def is_allowed(namespace: str, allow: Collection[str] | None) -> bool:
    """Whether ``plugins.allow`` permits a plugin namespace. The built-in one always is."""
    return allow is None or namespace == BUILTIN_NAMESPACE or namespace in allow


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


class Registry:
    """The contributions one harness can use. Plugins are imported on first reference.

    Args:
        catalog: Where installed plugins are found.
        allow: The org's ``plugins.allow`` list; ``None`` allows every namespace.
            The built-in plugin is always allowed.
        local: Modules listed under ``plugins.local``; they're imported now.
    """

    def __init__(
        self,
        catalog: PluginCatalog,
        *,
        allow: Iterable[str] | None = None,
        local: Iterable[str] = (),
    ) -> None:
        self._catalog = catalog
        self._allow = frozenset(allow) if allow is not None else None
        self._items: dict[tuple[str, str], Contribution] = {}
        self._plugins: dict[str, LoadedPlugin] = {}
        for target in local:
            loaded = catalog.load_local(target)
            if loaded.plugin.namespace in self._plugins:
                raise PluginConflict(
                    f"two plugins.local modules use namespace {loaded.plugin.namespace!r}",
                    namespace=loaded.plugin.namespace,
                )
            self._check_allowed(loaded.plugin.namespace)
            self._register(loaded)

    @property
    def catalog(self) -> PluginCatalog:
        return self._catalog

    def plugins(self) -> list[LoadedPlugin]:
        """The plugins registered so far, in registration order."""
        return list(self._plugins.values())

    def _check_allowed(self, namespace: str) -> None:
        if not is_allowed(namespace, self._allow):
            allowed = ", ".join(sorted(self._allow or ())) or "(none)"
            raise PluginNotAllowed(
                f"plugin namespace {namespace!r} isn't in plugins.allow ({allowed})",
                namespace=namespace,
            )

    def ensure(self, namespace: str) -> LoadedPlugin:
        """Allow-check, import and register the plugin that owns ``namespace``."""
        owner = BUILTIN_NAMESPACE if namespace in RESERVED_NAMESPACES else namespace
        if owner in self._plugins:
            return self._plugins[owner]
        self._check_allowed(owner)
        loaded = self._catalog.load(owner)
        self._register(loaded)
        return loaded

    def _register(self, loaded: LoadedPlugin) -> None:
        plugin = loaded.plugin
        if not plugin.contract_range.contains(CONTRACT_VERSION):
            raise IncompatibleContract(
                f"plugin {plugin.namespace!r} {plugin.version} supports contract "
                f"{plugin.contract}, but this core implements {CONTRACT_VERSION} (V5)",
                namespace=plugin.namespace,
            )
        staged: dict[tuple[str, str], Contribution] = {}
        for item in plugin.contributions():
            problem = check_owned(plugin, item)
            if problem is not None:
                raise PluginConflict(problem, namespace=plugin.namespace, name=item.name)
            contract = item.contract
            if contract is not None and not contract.contains(CONTRACT_VERSION):
                raise IncompatibleContract(
                    f"{item.name} supports contract {contract}, but this core implements "
                    f"{CONTRACT_VERSION} (V5)",
                    name=item.name,
                )
            info = item.item
            probabilistic_policy = (
                isinstance(info, ProviderInfo)
                and info.port == "PolicyEngine"
                and not info.deterministic
            )
            if probabilistic_policy:
                raise SpecError(
                    f"{item.name} is a probabilistic PolicyEngine; policy must be "
                    f"deterministic (RULES R3)",
                    name=item.name,
                )
            if item.key in staged or item.key in self._items:
                raise PluginConflict(
                    f"{item.name} is contributed twice", namespace=plugin.namespace
                )
            staged[item.key] = item
        self._items.update(staged)
        self._plugins[plugin.namespace] = loaded

    def _lookup(self, key: str, name: str, what: str) -> Contribution:
        loaded = self.ensure(namespace_of(name))
        found = self._items.get((key, name))
        if found is None:
            offered = sorted(
                n for (k, n) in self._items if k == key and owner_of(n) == loaded.plugin.namespace
            )
            hint = f"; it provides: {', '.join(offered)}" if offered else ""
            raise UnknownProvider(
                f"no {what} named {name!r} in plugin {loaded.plugin.namespace!r}{hint}",
                name=name,
            )
        return found

    def provider(self, port: str, name: str) -> ProviderInfo:
        """The provider ``name`` for ``port``.

        Raises:
            UnknownProvider, PluginNotAllowed, PluginConflict, IncompatibleContract.
        """
        item = self._lookup(port, name, f"{port} provider").item
        assert isinstance(item, ProviderInfo)
        return item

    def middleware(self, name: str) -> MiddlewareDef:
        """The middleware ``name`` (see :meth:`provider` for what it raises)."""
        item = self._lookup("middleware", name, "middleware").item
        assert isinstance(item, MiddlewareDef)
        return item

    def runner(self, name: str) -> RunnerInfo:
        """The runner ``name`` (see :meth:`provider` for what it raises)."""
        item = self._lookup("runner", name, "runner").item
        assert isinstance(item, RunnerInfo)
        return item

    def adapter(self, name: str) -> AdapterInfo:
        """The adapter ``name`` (see :meth:`provider` for what it raises)."""
        item = self._lookup("adapter", name, "adapter").item
        assert isinstance(item, AdapterInfo)
        return item

    def adapters(self) -> list[AdapterInfo]:
        """Adapters from the plugins registered so far."""
        return [c.item for c in self._items.values() if isinstance(c.item, AdapterInfo)]

    def names(self, key: str) -> list[str]:
        """Registered names for a port, or for ``middleware`` / ``runner`` / ``adapter``."""
        return sorted(name for (k, name) in self._items if k == key)
