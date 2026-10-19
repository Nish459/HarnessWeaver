"""Per-harness registration: the contributions one harness may use (C4)."""

from collections.abc import Collection, Iterable

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
    RESERVED_NAMESPACES,
    AdapterInfo,
    Contribution,
    ProviderInfo,
    RunnerInfo,
    check_owned,
    namespace_of,
)
from harnessweaver.core.registry.catalog import LoadedPlugin, PluginCatalog

__all__ = ["Registry", "is_allowed", "owner_of"]


def owner_of(name: str) -> str:
    """The namespace of the plugin that owns ``name`` (fixtures suite ``plugins``)."""
    space = namespace_of(name)
    return BUILTIN_NAMESPACE if space in RESERVED_NAMESPACES else space


def is_allowed(namespace: str, allow: Collection[str] | None) -> bool:
    """Whether ``plugins.allow`` permits a plugin namespace. The built-in one always is."""
    return allow is None or namespace == BUILTIN_NAMESPACE or namespace in allow


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
