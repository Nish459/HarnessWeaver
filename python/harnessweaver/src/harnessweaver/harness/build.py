"""Building a harness's parts from its spec: telemetry, models, middleware, tasks (R4)."""

from typing import Any

from pydantic import JsonValue

from harnessweaver._imports import import_object
from harnessweaver.core.bus import HookBus
from harnessweaver.core.context import ModelAccess, TaskInfo
from harnessweaver.core.envelope import Budget
from harnessweaver.core.errors import (
    SpecError,
    UnreachableHook,
)
from harnessweaver.core.hooks import Band, HookPoint
from harnessweaver.core.middleware import Registration
from harnessweaver.core.plugins import namespace_of
from harnessweaver.core.ports import ModelProvider, ToolBackend
from harnessweaver.core.registry import Registry
from harnessweaver.core.telemetry import Telemetry
from harnessweaver.harness.records import TaskEntry
from harnessweaver.modules.prompts import PromptStore
from harnessweaver.spec.loader import EffectiveSpec
from harnessweaver.spec.models import HarnessSpec, MiddlewareSpec, TaskSpec

__all__ = [
    "build_task",
    "build_telemetry",
    "install_middleware",
    "model_access",
    "required_hooks",
    "unsupported_sections",
]

MODEL_LIMITS = ("max_usd", "max_tokens", "max_model_calls")


def unsupported_sections(spec: HarnessSpec) -> list[str]:
    """Spec sections whose modules this release doesn't have yet.

    Loading such a spec fails rather than silently skipping a control (R4).
    """
    found: list[str] = []
    if spec.routing:
        found.append("routing")
    if spec.context:
        found.append("context")
    if spec.evals.online is not None and spec.evals.online.sample_rate > 0:
        found.append("evals.online")
    if spec.sidecar.url is not None:
        found.append("sidecar")
    return found


def import_type(path: str | None, what: str) -> type[Any] | None:
    if path is None:
        return None
    if path == "str":
        return str
    value = import_object(path, what)
    if not isinstance(value, type):
        raise SpecError(f"{what}: {path!r} is not a type")
    return value


def required_hooks(bus: HookBus, budget: Budget, task: str | None) -> set[HookPoint]:
    """Hooks a runner or adapter must reach: baseline middleware and budgets (R4)."""
    required = set(bus.hooks_in_band(Band.BASELINE, task))
    if budget.max_tool_calls is not None:
        required.add(HookPoint.TOOL_BEFORE)
    if any(getattr(budget, limit) is not None for limit in MODEL_LIMITS):
        required.update({HookPoint.MODEL_BEFORE, HookPoint.MODEL_AFTER})
    return required


def middleware_name(item: MiddlewareSpec, duplicates: set[str]) -> str:
    return f"{item.use}[{item.id}]" if item.use in duplicates and item.id else item.use


def build_telemetry(spec: HarnessSpec, registry: Registry) -> Telemetry:
    settings = spec.observability
    if settings.configure_sdk:
        setup = registry.provider("Telemetry", "otel.sdk").build(settings.provider_settings())
        setup.configure(
            service_name=settings.service_name or spec.metadata.name,
            exporter=settings.exporter,
            endpoint=settings.endpoint,
        )
    elif settings.exporter != "none":
        raise SpecError(
            f"observability.exporter: {settings.exporter} needs observability.configure_sdk: "
            "true; otherwise the app's own OpenTelemetry setup decides where spans go (R5)"
        )
    return Telemetry(capture_content=settings.capture_content)


def model_access(
    spec: HarnessSpec, registry: Registry, override: ModelProvider | None = None
) -> ModelAccess:
    models = spec.models
    provider: ModelProvider | None = override
    if provider is None and models.provider is not None:
        provider = registry.provider("ModelProvider", models.provider).build(
            models.provider_settings()
        )
    prices = {name: (p.input_per_mtok, p.output_per_mtok) for name, p in models.prices.items()}
    allowed = frozenset(models.allowed_aliases) if models.allowed_aliases is not None else None
    return ModelAccess(
        provider=provider,
        default_alias=models.default,
        aliases=dict(models.aliases),
        allowed_aliases=allowed,
        prices=prices.get if prices else None,
        provider_name=(
            type(override).__name__
            if override is not None
            else namespace_of(models.provider)
            if models.provider
            else None
        ),
    )


def install_middleware(spec: HarnessSpec, registry: Registry, bus: HookBus) -> None:
    uses = [item.use for item in spec.middleware]
    duplicates = {use for use in uses if uses.count(use) > 1}
    for item in spec.middleware:
        if not item.enabled:
            continue
        declared = registry.middleware(item.use)
        hooks = tuple(item.hooks) if item.hooks is not None else declared.hooks
        extra = [h.value for h in hooks if h not in declared.hooks]
        if extra:
            raise SpecError(
                f"middleware[{item.id}].hooks: {item.use} doesn't attach to "
                f"{', '.join(extra)}; it declares {', '.join(h.value for h in declared.hooks)}"
            )
        bus.add(
            Registration(
                name=middleware_name(item, duplicates),
                handler=declared.build(item.provider_settings()),
                hooks=frozenset(hooks),
                band=item.band or declared.band,
                fail_mode=item.fail_mode or declared.fail_mode,
                timeout=item.timeout if item.timeout is not None else declared.timeout,
            )
        )


def build_task(
    effective: EffectiveSpec,
    name: str,
    task: TaskSpec,
    registry: Registry,
    bus: HookBus,
    models: ModelAccess,
    prompts: PromptStore,
    tools: ToolBackend | None,
) -> TaskEntry:
    where = f"tasks.{name}"
    info = registry.runner(task.runner.use)
    runner = info.build(task.runner.provider_settings())
    required = required_hooks(bus, effective.run_budget(name), name)
    missing = sorted(h.value for h in required - info.reaches)
    if missing:
        raise UnreachableHook(
            f"{where}: runner {info.name} can't reach {', '.join(missing)}, which the "
            f"baseline needs (RULES R4)",
            task=name,
            hooks=list[JsonValue](missing),
        )
    if info.name == "direct" and models.provider is None:
        raise SpecError(f"{where} uses the direct runner, which needs models.provider")
    if task.prompt is not None:
        prompts.find(task.prompt)
    for tool in task.tools:
        if tools is None or tools.describe(tool) is None:
            raise SpecError(f"{where}.tools: no tool named {tool!r}", task=name, tool=tool)
    validation = effective.spec.validation
    return TaskEntry(
        name=name,
        spec=task,
        info=TaskInfo(
            name=name,
            version=task.version,
            model=task.model,
            prompt=task.prompt,
            tools=task.tools,
            input_type=import_type(task.input, f"{where}.input"),
            output_type=import_type(task.output, f"{where}.output"),
            max_repairs=validation.max_repairs,
            on_failure=validation.on_failure,
        ),
        runner=runner,
        runner_name=info.name,
        resumable=info.resumable,
    )
