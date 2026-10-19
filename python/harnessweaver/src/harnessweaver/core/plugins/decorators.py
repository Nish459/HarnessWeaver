"""The decorators that declare contributions, and the metadata they attach.

Decorating registers nothing: it only attaches an info object (S8).
"""

import inspect
from collections.abc import Awaitable, Callable, Iterable, Mapping
from dataclasses import dataclass
from typing import Any, Final, Literal

from pydantic import BaseModel, ValidationError

from harnessweaver.core.decisions import Decision, DecisionRequest
from harnessweaver.core.errors import SpecError
from harnessweaver.core.hooks import HookPoint
from harnessweaver.core.plugins.names import (
    DEFAULT_CONTRACT,
    LATENCY_CLASSES,
    PORTS,
    check_name,
    parse_contract,
)
from harnessweaver.core.semver import VersionRange

__all__ = [
    "AdapterInfo",
    "ProviderInfo",
    "RunnerInfo",
    "adapter",
    "adapter_info",
    "decider",
    "provider",
    "provider_info",
    "runner",
    "runner_info",
]


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
    contract: str = DEFAULT_CONTRACT,
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
    checked, range_, stage_names = check_name(name), parse_contract(contract), tuple(stages)

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
    name: str, *, deterministic: bool = True, contract: str = DEFAULT_CONTRACT
) -> Callable[
    [Callable[[DecisionRequest], Awaitable[Decision]]],
    Callable[[DecisionRequest], Awaitable[Decision]],
]:
    """Declare an async function as a routing stage (``Decider`` port, DESIGNS No. 19)."""
    checked = check_name(name)
    range_ = parse_contract(contract)

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
    contract: str = DEFAULT_CONTRACT,
    resumable: bool = False,
    sample: Mapping[str, Any] | None = None,
) -> Callable[[type[T]], type[T]]:
    """Declare a class as a runner (DESIGNS No. 15).

    ``reaches`` must be honest: loading fails if the baseline needs a hook point
    the runner can't fire (R4). ``resumable`` runners continue from a checkpoint
    after an approval; others re-run their interrupted step.
    """
    checked, range_ = check_name(name), parse_contract(contract)
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
    contract: str = DEFAULT_CONTRACT,
    sample: Callable[[], Any] | None = None,
) -> Callable[[type[T]], type[T]]:
    """Declare a class as an adapter for ``harness.wrap()`` / ``harness.instrument()``.

    ``wraps`` lists the fully qualified type names it accepts, such as
    ``"openai.AsyncOpenAI"``; they are matched by name, so nothing is imported.
    """
    checked, range_, types = check_name(name), parse_contract(contract), tuple(wraps)
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
