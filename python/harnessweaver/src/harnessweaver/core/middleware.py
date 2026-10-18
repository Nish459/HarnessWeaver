"""Middleware: functions or classes attached to hook points (DESIGNS No. 8).

``@hw.middleware`` declares a middleware. Declaring one activates nothing: the
spec's ``middleware:`` list selects it and assigns its band (S8), or a module
installs it. A middleware returns an :data:`~harnessweaver.Outcome` (or ``None``
for ``Continue()``) and never raises for control flow. If it raises or times
out anyway, its declared ``fail_mode`` decides what happens (R2, ADR-0014).
"""

import inspect
import re
from collections.abc import Awaitable, Callable, Iterable, Mapping
from dataclasses import dataclass
from datetime import timedelta
from typing import Any, Literal, cast

from pydantic import BaseModel, ValidationError

from harnessweaver.core.durations import parse_duration
from harnessweaver.core.envelope import Envelope
from harnessweaver.core.errors import SpecError
from harnessweaver.core.hooks import Band, HookPoint
from harnessweaver.core.outcomes import Outcome

__all__ = [
    "FAIL_MODES",
    "FailMode",
    "Handler",
    "MiddlewareDef",
    "Registration",
    "middleware",
]

type FailMode = Literal["closed", "open"]
type Handler = Callable[[Any, Envelope], Awaitable[Outcome | None]]
"""An installed middleware: ``async (event, envelope) -> Outcome | None``."""

FAIL_MODES: tuple[FailMode, ...] = ("closed", "open")

_NAME = re.compile(r"^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)*$")


def _default_name(target: Callable[..., Any]) -> str:
    # Classes are CamelCase; names are snake_case (RULES C8).
    return re.sub(r"(?<!^)(?=[A-Z])", "_", target.__name__).lower()


def _hooks(hooks: Iterable[HookPoint | str]) -> tuple[HookPoint, ...]:
    parsed: list[HookPoint] = []
    for hook in hooks:
        try:
            point = HookPoint(hook)
        except ValueError:
            known = ", ".join(h.value for h in HookPoint)
            raise ValueError(f"unknown hook point {hook!r}; known: {known}") from None
        if point not in parsed:
            parsed.append(point)
    if not parsed:
        raise ValueError("a middleware must attach to at least one hook point")
    return tuple(parsed)


def _fail_mode(value: str) -> FailMode:
    if value not in FAIL_MODES:
        raise ValueError(f"fail_mode must be 'closed' or 'open', not {value!r} (ADR-0014)")
    return value


def _timeout(value: timedelta | str | float | None) -> timedelta | None:
    if value is None:
        return None
    timeout = parse_duration(value)
    if timeout <= timedelta(0):
        raise ValueError("a middleware timeout must be positive")
    return timeout


@dataclass(frozen=True, slots=True)
class MiddlewareDef:
    """A declared middleware, as contributed by a plugin.

    Attributes:
        name: The name given to the decorator; a plugin qualifies a bare name
            with its namespace (``acme.no_weekend_refunds``).
        target: The decorated async function, or a class whose instances are
            async callables. A class is built with its ``config`` model.
        hooks: The hook points it attaches to. A spec may narrow them.
        band: The band it runs in when the spec doesn't assign one.
        fail_mode: What a raise or timeout turns into: ``closed`` -> ``Block``,
            ``open`` -> ``Continue`` plus a trace record.
        timeout: How long one call may take, or ``None`` for no limit.
        config: The settings model for a class middleware.
    """

    name: str
    target: Callable[..., Any]
    hooks: tuple[HookPoint, ...]
    band: Band
    fail_mode: FailMode
    timeout: timedelta | None
    config: type[BaseModel] | None = None
    description: str | None = None
    sample: Mapping[str, Any] | None = None
    """Settings the conformance suite builds a class middleware with (T5)."""

    @property
    def is_class(self) -> bool:
        return inspect.isclass(self.target)

    async def __call__(self, event: Any, env: Envelope) -> Outcome | None:
        """Call a function middleware directly, for tests."""
        if self.is_class:
            raise TypeError(f"{self.name} is a class middleware; build() it first")
        return await self.target(event, env)

    def build(self, settings: Mapping[str, Any] | None = None) -> Handler:
        """Return the callable to install, validating ``settings`` against ``config``.

        Raises:
            SpecError: If the settings are invalid, or given to a middleware
                that takes none.
        """
        settings = dict(settings or {})
        if not self.is_class:
            if settings:
                keys = ", ".join(sorted(settings))
                raise SpecError(f"middleware {self.name} takes no settings, got: {keys}")
            return cast("Handler", self.target)
        if self.config is None:
            if settings:
                keys = ", ".join(sorted(settings))
                raise SpecError(f"middleware {self.name} takes no settings, got: {keys}")
            return cast("Handler", self.target())
        try:
            config = self.config.model_validate(settings)
        except ValidationError as exc:
            problems = "; ".join(
                f"{'.'.join(str(p) for p in e['loc']) or '(settings)'}: {e['msg']}"
                for e in exc.errors()
            )
            raise SpecError(f"middleware {self.name} settings: {problems}") from None
        return cast("Handler", self.target(config))


def middleware(
    *,
    hooks: Iterable[HookPoint | str],
    fail_mode: FailMode,
    band: Band | str = Band.APP,
    timeout: timedelta | str | float | None = None,
    name: str | None = None,
    config: type[BaseModel] | None = None,
    sample: Mapping[str, Any] | None = None,
) -> Callable[[Callable[..., Any]], MiddlewareDef]:
    """Declare a middleware (DESIGNS No. 8).

    ``fail_mode`` is required (R2, ADR-0014). ``band`` is only a default for when
    the spec doesn't assign one, and it can't be ``baseline``: only the org
    baseline profile puts middleware there (S8).

    Example:
        >>> @middleware(hooks=["tool.before"], fail_mode="closed", timeout="2s")
        ... async def no_weekend_refunds(event, env):
        ...     return None

    Raises:
        ValueError: For an unknown hook or fail mode, the
            baseline band, or a non-positive timeout.
        TypeError: If the target isn't an async function or a class.
    """

    def declare(func: Callable[..., Any]) -> MiddlewareDef:
        declared_band = Band(band)
        if declared_band is Band.BASELINE:
            raise ValueError(
                "a middleware can't declare the baseline band; the org baseline "
                "profile assigns it in the spec (RULES S8)"
            )
        is_class = inspect.isclass(func)
        if not is_class and not inspect.iscoroutinefunction(func):
            raise TypeError(f"middleware {func.__name__} must be an async function or a class")
        if config is not None and not is_class:
            raise TypeError("only a class middleware can take a config model")
        declared_name = name or _default_name(func)
        if not _NAME.match(declared_name):
            raise ValueError(f"invalid middleware name {declared_name!r}: use lowercase words")
        return MiddlewareDef(
            name=declared_name,
            target=func,
            hooks=_hooks(hooks),
            band=declared_band,
            fail_mode=_fail_mode(fail_mode),
            timeout=_timeout(timeout),
            config=config,
            description=inspect.getdoc(func),
            sample=dict(sample) if sample is not None else None,
        )

    return declare


@dataclass(frozen=True, slots=True)
class Registration:
    """A middleware installed on a harness's hook bus."""

    name: str
    handler: Handler
    hooks: frozenset[HookPoint]
    band: Band
    fail_mode: FailMode
    timeout: timedelta | None = None
    tasks: frozenset[str] | None = None
    """Only run for these tasks; ``None`` means every task and session."""

    def applies_to(self, hook: HookPoint, task: str | None) -> bool:
        return hook in self.hooks and (self.tasks is None or task in self.tasks)
