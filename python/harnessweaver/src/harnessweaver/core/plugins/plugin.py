"""``hw.Plugin``: everything one package contributes, and the namespace checks."""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal

from harnessweaver.core.errors import SpecError
from harnessweaver.core.middleware import MiddlewareDef
from harnessweaver.core.plugins.decorators import (
    AdapterInfo,
    ProviderInfo,
    RunnerInfo,
    adapter_info,
    provider_info,
    runner_info,
)
from harnessweaver.core.plugins.names import (
    BUILTIN_NAMESPACE,
    DEFAULT_CONTRACT,
    NAMESPACE_PATTERN,
    RESERVED_NAMESPACES,
    check_name,
    namespace_of,
    parse_contract,
    qualify,
)
from harnessweaver.core.semver import Version, VersionRange

__all__ = ["Contribution", "Plugin", "as_plugin", "check_owned"]

type ContributionKind = Literal["provider", "middleware", "runner", "adapter"]


@dataclass(frozen=True, slots=True)
class Contribution:
    """One named thing a plugin contributes, with its qualified name."""

    kind: ContributionKind
    name: str
    port: str | None
    item: ProviderInfo | MiddlewareDef | RunnerInfo | AdapterInfo

    @property
    def key(self) -> tuple[str, str]:
        """Registry key: names are unique per port (``memory`` is a state store and an
        approval channel), and per kind for everything else."""
        return (self.port or self.kind, self.name)

    @property
    def contract(self) -> VersionRange | None:
        return None if isinstance(self.item, MiddlewareDef) else self.item.contract


@dataclass(frozen=True, slots=True)
class Plugin:
    """A plugin: everything one package or module contributes (DESIGNS No. 13).

    Example:
        >>> plugin = Plugin(
        ...     namespace="acme",
        ...     version="1.2.0",
        ...     providers=[InHousePII],
        ...     middleware=[no_weekend_refunds],
        ...     profiles={"baseline": "profiles/baseline.yaml"},
        ... )  # doctest: +SKIP

    Attributes:
        namespace: Owns every name ``<namespace>.*``. For an installed plugin it
            must equal the entry-point name.
        version: The plugin's own SemVer version.
        contract: The ``harnessweaver/v1`` contract range it was built against (V5).
        providers: Classes decorated with ``@hw.provider`` and functions
            decorated with ``@hw.decider``.
        middleware: Objects made by ``@hw.middleware``.
        runners: Classes decorated with ``@hw.runner``.
        adapters: Classes decorated with ``@hw.adapter``.
        profiles: ``name -> path`` of profile files inside the plugin's package,
            referenced as ``profile://<namespace>.<name>``.
        templates: ``name -> path`` of project templates for ``harnessweaver init``.
    """

    namespace: str
    version: str
    contract: str = DEFAULT_CONTRACT
    providers: Sequence[object] = ()
    middleware: Sequence[MiddlewareDef] = ()
    runners: Sequence[type[Any]] = ()
    adapters: Sequence[type[Any]] = ()
    profiles: Mapping[str, str] = field(default_factory=dict[str, str])
    templates: Mapping[str, str] = field(default_factory=dict[str, str])
    description: str | None = None

    def __post_init__(self) -> None:
        if not NAMESPACE_PATTERN.match(self.namespace):
            raise ValueError(
                f"invalid plugin namespace {self.namespace!r}: use lowercase letters, "
                "digits and underscores, starting with a letter"
            )
        try:
            Version.parse(self.version)
        except ValueError as exc:
            raise ValueError(f"plugin {self.namespace}: invalid version: {exc}") from None
        parse_contract(self.contract)
        for item in self.middleware:
            if not isinstance(item, MiddlewareDef):  # pyright: ignore[reportUnnecessaryIsInstance]
                raise TypeError(f"plugin {self.namespace}: {item!r} isn't an @hw.middleware")
        for name in [*self.profiles, *self.templates]:
            check_name(name)
        self.contributions()  # fail now on undecorated items

    @property
    def contract_range(self) -> VersionRange:
        return parse_contract(self.contract)

    def contributions(self) -> list[Contribution]:
        """Everything this plugin contributes, with qualified names.

        Raises:
            TypeError: If an item isn't decorated.
        """
        items: list[Contribution] = []
        for obj in self.providers:
            info = provider_info(obj)
            items.append(
                Contribution("provider", qualify(self.namespace, info.name), info.port, info)
            )
        for mw in self.middleware:
            items.append(Contribution("middleware", qualify(self.namespace, mw.name), None, mw))
        for cls in self.runners:
            run = runner_info(cls)
            items.append(Contribution("runner", qualify(self.namespace, run.name), None, run))
        for cls in self.adapters:
            adp = adapter_info(cls)
            items.append(Contribution("adapter", qualify(self.namespace, adp.name), None, adp))
        return items


def check_owned(plugin: Plugin, contribution: Contribution) -> str | None:
    """Why ``contribution`` sits outside ``plugin``'s namespace, or ``None`` if it's fine."""
    space = namespace_of(contribution.name)
    if plugin.namespace == BUILTIN_NAMESPACE:
        if space not in RESERVED_NAMESPACES:
            return f"built-in name {contribution.name!r} is outside the reserved namespaces"
        return None
    if space != plugin.namespace:
        return (
            f"plugin {plugin.namespace!r} contributes {contribution.name!r}, outside its namespace"
        )
    return None


def as_plugin(value: object, where: str) -> Plugin:
    """Check that an imported object is a :class:`Plugin`.

    Raises:
        SpecError: If it isn't.
    """
    if not isinstance(value, Plugin):
        raise SpecError(f"{where} is not a harnessweaver.Plugin (got {type(value).__name__})")
    return value
