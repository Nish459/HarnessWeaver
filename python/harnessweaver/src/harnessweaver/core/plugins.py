"""The plugin contract: ``hw.Plugin`` and the decorators that declare contributions.

A plugin is defined by its design, not its name (DESIGNS No. 13, ADR-0015). Any
importable module that exposes an :class:`Plugin` object is a plugin, found
through the ``harnessweaver.plugins`` entry-point group or ``plugins.local``.
First-party, third-party and built-in contributions all use this contract.

Declaring something registers nothing. Decorators only attach metadata, and a
``Plugin`` object is a plain description; a harness's registry imports and
registers a plugin only when its effective spec references the plugin's
namespace (S8).
"""

import inspect
import re
from collections.abc import Awaitable, Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Final, Literal

from pydantic import BaseModel, ValidationError

from harnessweaver.core.decisions import Decision, DecisionRequest
from harnessweaver.core.errors import SpecError
from harnessweaver.core.hooks import HookPoint
from harnessweaver.core.middleware import MiddlewareDef
from harnessweaver.core.semver import Version, VersionRange

__all__ = [
    "BUILTIN_NAMESPACE",
    "CONTRACT_VERSION",
    "ENTRY_POINT_GROUP",
    "LATENCY_CLASSES",
    "PORTS",
    "RESERVED_NAMESPACES",
    "AdapterInfo",
    "Contribution",
    "Plugin",
    "ProviderInfo",
    "RunnerInfo",
    "adapter",
    "decider",
    "namespace_of",
    "provider",
    "qualify",
    "runner",
]

CONTRACT_VERSION: Final = Version(1, 0, 0)
"""The version of the ``harnessweaver/v1`` contract this core implements (V5)."""

ENTRY_POINT_GROUP: Final = "harnessweaver.plugins"
"""Installed plugins expose their ``Plugin`` object in this entry-point group."""

BUILTIN_NAMESPACE: Final = "harnessweaver"
"""The namespace of the core's own built-in plugin."""

RESERVED_NAMESPACES: Final = frozenset(
    {
        BUILTIN_NAMESPACE,
        # runners
        "direct",
        "session",
        "workflow",
        # models, state, approvals, context
        "scripted",
        "memory",
        "sqlite",
        "callback",
        "console",
        "webhook",
        "passthrough",
        # policy, routing, validation
        "cel_lite",
        "rules",
        "lexical",
        "semantic",
        "llm",
        "pydantic",
        "json_schema",
        # guardrails
        "pii",
        "secrets",
        "regex",
        "injection",
        "size",
        "topic",
        "grounded",
    }
)
"""Namespaces owned by the built-in plugin. Bare names (``direct``) are their own
namespace. Other plugins can't claim these (DESIGNS No. 13)."""

PORTS: Final = frozenset(
    {
        "ApprovalChannel",
        "ContextProvider",
        "DatasetStore",
        "Decider",
        "Embedder",
        "ErrorClassifier",
        "Evaluator",
        "Guardrail",
        "Memory",
        "ModelProvider",
        "PolicyEngine",
        "Sandbox",
        "StateStore",
        "Telemetry",
        "ToolGovernor",
        "ToolRegistry",
        "Validator",
    }
)
"""The ports a provider can implement (DESIGNS No. 14)."""

LATENCY_CLASSES: Final = ("fast", "medium", "slow")
"""Declared latency classes; the conformance suite checks p95 against them."""

_NAMESPACE = re.compile(r"^[a-z][a-z0-9_]*$")
_NAME = re.compile(r"^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)*$")
_DEFAULT_CONTRACT: Final = ">=1.0,<2"


def namespace_of(name: str) -> str:
    """The namespace a name belongs to: the text before the first dot, or the bare name."""
    return name.split(".", 1)[0]


def qualify(namespace: str, name: str) -> str:
    """Give a bare contributed name its plugin's namespace.

    The built-in plugin keeps its names as written: they are bare or in a
    reserved namespace.
    """
    if namespace == BUILTIN_NAMESPACE or "." in name:
        return name
    return f"{namespace}.{name}"


def _contract(text: str) -> VersionRange:
    try:
        return VersionRange.parse(text)
    except ValueError as exc:
        raise ValueError(f"invalid contract range {text!r}: {exc}") from None


def _check_name(name: str) -> str:
    if not _NAME.match(name):
        raise ValueError(f"invalid name {name!r}: use lowercase words joined by dots")
    return name


def _build[C: BaseModel](
    what: str, target: Callable[..., Any], config: type[C] | None, settings: Mapping[str, Any]
) -> Any:
    """Construct a contribution from its config model alone (RULES C11)."""
    if config is None:
        if settings:
            raise SpecError(f"{what} takes no settings, got: {', '.join(sorted(settings))}")
        return target()
    try:
        validated = config.model_validate(dict(settings))
    except ValidationError as exc:
        problems = "; ".join(
            f"{'.'.join(str(p) for p in e['loc']) or '(settings)'}: {e['msg']}"
            for e in exc.errors()
        )
        raise SpecError(f"{what} settings: {problems}") from None
    return target(validated)


# --- providers -----------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ProviderInfo:
    """What ``@hw.provider`` (or ``@hw.decider``) declares about an implementation of a port."""

    port: str
    name: str
    target: Callable[..., Any]
    config: type[BaseModel] | None
    contract: VersionRange
    deterministic: bool
    latency_class: str
    stages: tuple[str, ...] = ()
    kind: Literal["class", "function"] = "class"
    sample: Mapping[str, Any] | None = None
    """Settings the conformance suite builds the provider with (T5)."""

    def build(self, settings: Mapping[str, Any] | None = None) -> Any:
        """Return a ready instance (or, for a function provider, the function).

        Raises:
            SpecError: If ``settings`` don't validate against the config model.
        """
        if self.kind == "function":
            if settings:
                raise SpecError(f"{self.name} takes no settings")
            return self.target
        return _build(f"provider {self.name}", self.target, self.config, settings or {})


_PROVIDER_ATTR: Final = "__harnessweaver_provider__"
_RUNNER_ATTR: Final = "__harnessweaver_runner__"
_ADAPTER_ATTR: Final = "__harnessweaver_adapter__"


def provider[T](
    *,
    port: str,
    name: str,
    config: type[BaseModel] | None = None,
    contract: str = _DEFAULT_CONTRACT,
    deterministic: bool = False,
    latency_class: str = "medium",
    stages: Iterable[str] = (),
    sample: Mapping[str, Any] | None = None,
) -> Callable[[type[T]], type[T]]:
    """Declare a class as a provider for ``port`` (DESIGNS No. 12).

    The class must be constructible from its config model alone (RULES C11).
    ``sample`` gives settings for the conformance suite when the config model
    has required fields (T5).

    Raises:
        ValueError: For an unknown port or latency class, a malformed name or
            contract range, or a probabilistic ``PolicyEngine`` (R3).
    """
    if port not in PORTS:
        raise ValueError(f"unknown port {port!r}; known: {', '.join(sorted(PORTS))}")
    if latency_class not in LATENCY_CLASSES:
        raise ValueError(f"latency_class must be one of {', '.join(LATENCY_CLASSES)}")
    if port == "PolicyEngine" and not deterministic:
        raise ValueError("a PolicyEngine must be deterministic=True (RULES R3)")
    checked, range_, stage_names = _check_name(name), _contract(contract), tuple(stages)

    def declare(cls: type[T]) -> type[T]:
        if not inspect.isclass(cls):
            raise TypeError("@provider decorates a class")
        info = ProviderInfo(
            port=port,
            name=checked,
            target=cls,
            config=config,
            contract=range_,
            deterministic=deterministic,
            latency_class=latency_class,
            stages=stage_names,
            sample=dict(sample) if sample is not None else None,
        )
        setattr(cls, _PROVIDER_ATTR, info)
        return cls

    return declare


def decider(
    name: str, *, deterministic: bool = True, contract: str = _DEFAULT_CONTRACT
) -> Callable[
    [Callable[[DecisionRequest], Awaitable[Decision]]],
    Callable[[DecisionRequest], Awaitable[Decision]],
]:
    """Declare an async function as a routing stage (``Decider`` port, DESIGNS No. 19)."""
    checked = _check_name(name)
    range_ = _contract(contract)

    def declare(
        func: Callable[[DecisionRequest], Awaitable[Decision]],
    ) -> Callable[[DecisionRequest], Awaitable[Decision]]:
        if not inspect.iscoroutinefunction(func):
            raise TypeError(f"decider {checked} must be an async function")
        info = ProviderInfo(
            port="Decider",
            name=checked,
            target=func,
            config=None,
            contract=range_,
            deterministic=deterministic,
            latency_class="fast",
            kind="function",
        )
        setattr(func, _PROVIDER_ATTR, info)
        return func

    return declare


def provider_info(obj: object) -> ProviderInfo:
    """The :class:`ProviderInfo` attached by ``@provider`` or ``@decider``.

    Raises:
        TypeError: If ``obj`` wasn't decorated.
    """
    info = getattr(obj, _PROVIDER_ATTR, None)
    if not isinstance(info, ProviderInfo):
        raise TypeError(f"{obj!r} isn't decorated with @hw.provider or @hw.decider")
    return info


# --- runners and adapters ------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class RunnerInfo:
    """What ``@hw.runner`` declares. ``reaches`` lists the hook points it can fire (R4)."""

    name: str
    target: Callable[..., Any]
    reaches: frozenset[HookPoint]
    config: type[BaseModel] | None
    contract: VersionRange
    resumable: bool = False
    sample: Mapping[str, Any] | None = None
    """Settings the conformance suite runs a task with (T5)."""

    def build(self, settings: Mapping[str, Any] | None = None) -> Any:
        """Return a ready runner, with its settings validated (RULES C11)."""
        return _build(f"runner {self.name}", self.target, self.config, settings or {})


def runner[T](
    name: str,
    *,
    reaches: Iterable[HookPoint | str],
    config: type[BaseModel] | None = None,
    contract: str = _DEFAULT_CONTRACT,
    resumable: bool = False,
    sample: Mapping[str, Any] | None = None,
) -> Callable[[type[T]], type[T]]:
    """Declare a class as a runner (DESIGNS No. 15).

    ``reaches`` must be honest: loading fails if the baseline needs a hook point
    the runner can't fire (R4). ``resumable`` runners continue from a checkpoint
    after an approval; others re-run their interrupted step.
    """
    checked, range_ = _check_name(name), _contract(contract)
    hooks = frozenset(HookPoint(h) for h in reaches)

    def declare(cls: type[T]) -> type[T]:
        if not inspect.isclass(cls):
            raise TypeError("@runner decorates a class")
        settings = dict(sample) if sample is not None else None
        info = RunnerInfo(checked, cls, hooks, config, range_, resumable, settings)
        setattr(cls, _RUNNER_ATTR, info)
        return cls

    return declare


def runner_info(obj: object) -> RunnerInfo:
    info = getattr(obj, _RUNNER_ATTR, None)
    if not isinstance(info, RunnerInfo):
        raise TypeError(f"{obj!r} isn't decorated with @hw.runner")
    return info


@dataclass(frozen=True, slots=True)
class AdapterInfo:
    """What ``@hw.adapter`` declares: the types it wraps and the hooks it reaches (R4)."""

    name: str
    target: Callable[..., Any]
    wraps: tuple[str, ...]
    reaches: frozenset[HookPoint]
    contract: VersionRange
    sample: Callable[[], Any] | None = None
    """Returns ``(target, call)`` for the conformance suite: an object to wrap and an
    async function that makes one call through the wrapped object (T5)."""


def adapter[T](
    name: str,
    *,
    wraps: Iterable[str],
    reaches: Iterable[HookPoint | str],
    contract: str = _DEFAULT_CONTRACT,
    sample: Callable[[], Any] | None = None,
) -> Callable[[type[T]], type[T]]:
    """Declare a class as an adapter for ``harness.wrap()`` / ``harness.instrument()``.

    ``wraps`` lists the fully qualified type names it accepts, such as
    ``"openai.AsyncOpenAI"``; they are matched by name, so nothing is imported.
    """
    checked, range_, types = _check_name(name), _contract(contract), tuple(wraps)
    hooks = frozenset(HookPoint(h) for h in reaches)

    def declare(cls: type[T]) -> type[T]:
        if not inspect.isclass(cls):
            raise TypeError("@adapter decorates a class")
        setattr(cls, _ADAPTER_ATTR, AdapterInfo(checked, cls, types, hooks, range_, sample))
        return cls

    return declare


def adapter_info(obj: object) -> AdapterInfo:
    info = getattr(obj, _ADAPTER_ATTR, None)
    if not isinstance(info, AdapterInfo):
        raise TypeError(f"{obj!r} isn't decorated with @hw.adapter")
    return info


# --- the plugin object ---------------------------------------------------------------------

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
    contract: str = _DEFAULT_CONTRACT
    providers: Sequence[object] = ()
    middleware: Sequence[MiddlewareDef] = ()
    runners: Sequence[type[Any]] = ()
    adapters: Sequence[type[Any]] = ()
    profiles: Mapping[str, str] = field(default_factory=dict[str, str])
    templates: Mapping[str, str] = field(default_factory=dict[str, str])
    description: str | None = None

    def __post_init__(self) -> None:
        if not _NAMESPACE.match(self.namespace):
            raise ValueError(
                f"invalid plugin namespace {self.namespace!r}: use lowercase letters, "
                "digits and underscores, starting with a letter"
            )
        try:
            Version.parse(self.version)
        except ValueError as exc:
            raise ValueError(f"plugin {self.namespace}: invalid version: {exc}") from None
        _contract(self.contract)
        for item in self.middleware:
            if not isinstance(item, MiddlewareDef):  # pyright: ignore[reportUnnecessaryIsInstance]
                raise TypeError(f"plugin {self.namespace}: {item!r} isn't an @hw.middleware")
        for name in [*self.profiles, *self.templates]:
            _check_name(name)
        self.contributions()  # fail now on undecorated items

    @property
    def contract_range(self) -> VersionRange:
        return _contract(self.contract)

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
