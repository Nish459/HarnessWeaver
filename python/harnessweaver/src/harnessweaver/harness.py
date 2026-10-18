"""Harness: the runtime object an app builds from its spec (DESIGNS No. 6, No. 7, No. 18).

```python
harness = hw.Harness.load("harness.yaml")
result = await harness.run("extract_invoice", doc, principal="alice")
```

Loading resolves every name the spec references through the plugin registry,
installs the spec's middleware on the hook bus, builds each task's runner and
checks that the runner reaches every hook the baseline needs (R4). Anything
wrong fails here, at load, never at run time.
"""

import contextlib
import logging
import math
from collections.abc import AsyncIterator, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import timedelta
from pathlib import Path
from types import TracebackType
from typing import Any, Literal, Self

import anyio
from anyio.abc import TaskGroup
from anyio.streams.memory import MemoryObjectSendStream
from opentelemetry.trace import Span
from pydantic import BaseModel, JsonValue, ValidationError

from harnessweaver._imports import import_object
from harnessweaver.adapters import Binding
from harnessweaver.core.budgets import BudgetMeter
from harnessweaver.core.bus import HookBus
from harnessweaver.core.context import ModelAccess, RunContext, TaskInfo
from harnessweaver.core.envelope import Budget, Clock, Envelope, Principal, SystemClock
from harnessweaver.core.errors import (
    DeadlineExceeded,
    HarnessError,
    NotFound,
    PolicyDenied,
    RunBlocked,
    RunEscalated,
    RunInterrupted,
    RunSuspended,
    SpecError,
    UnknownProvider,
    UnreachableHook,
    ValidationFailed,
    classify,
    from_known,
)
from harnessweaver.core.hooks import Band, HookPoint, RunEndEvent, RunErrorEvent, RunStartEvent
from harnessweaver.core.ids import new_id
from harnessweaver.core.messages import StreamChunk
from harnessweaver.core.middleware import Registration
from harnessweaver.core.outcomes import Retry
from harnessweaver.core.plugins import AdapterInfo, namespace_of
from harnessweaver.core.ports import ModelProvider, Runner, StateStore, ToolBackend
from harnessweaver.core.registry import PluginCatalog, Registry
from harnessweaver.core.results import RunEvent, RunResult
from harnessweaver.core.runs import ApprovalDecision, ApprovalRequest, RunStatus
from harnessweaver.core.state import Checkpoint, Grant, RunRecord
from harnessweaver.core.telemetry import Telemetry
from harnessweaver.core.trace import RunTrace, TraceEvent
from harnessweaver.modules.guardrails import install_guardrails
from harnessweaver.modules.prompts import PromptStore
from harnessweaver.modules.validation import install_validation
from harnessweaver.runners._output import to_json
from harnessweaver.session import Session
from harnessweaver.spec.explain import ExplainRow
from harnessweaver.spec.loader import EffectiveSpec, load_spec
from harnessweaver.spec.models import HarnessSpec, MiddlewareSpec, TaskApprovals, TaskSpec

__all__ = ["Harness"]

_log = logging.getLogger("harnessweaver.harness")

_MODEL_LIMITS = ("max_usd", "max_tokens", "max_model_calls")

type ApprovalAnswer = Literal["approve", "reject", "edit"]


def _unsupported(spec: HarnessSpec) -> list[str]:
    """Spec sections whose modules this release doesn't have yet.

    Loading such a spec fails rather than silently skipping a control (R4).
    """
    found: list[str] = []
    for name, task in spec.tasks.items():
        if task.approvals is not None and task.approvals.tools:
            found.append(f"tasks.{name}.approvals.tools")
    if spec.policy.rules or spec.policy.use != "cel_lite":
        found.append("policy")
    if spec.approvals.use != "memory":
        found.append("approvals.use")
    if spec.tools.manifests:
        found.append("tools.manifests")
    if spec.routing:
        found.append("routing")
    if spec.context:
        found.append("context")
    if spec.evals.online is not None and spec.evals.online.sample_rate > 0:
        found.append("evals.online")
    if spec.sidecar.url is not None:
        found.append("sidecar")
    return found


def _import_type(path: str | None, what: str) -> type[Any] | None:
    if path is None:
        return None
    if path == "str":
        return str
    value = import_object(path, what)
    if not isinstance(value, type):
        raise SpecError(f"{what}: {path!r} is not a type")
    return value


def _required_hooks(bus: HookBus, budget: Budget, task: str | None) -> set[HookPoint]:
    """Hooks a runner or adapter must reach: baseline middleware and budgets (R4)."""
    required = set(bus.hooks_in_band(Band.BASELINE, task))
    if budget.max_tool_calls is not None:
        required.add(HookPoint.TOOL_BEFORE)
    if any(getattr(budget, limit) is not None for limit in _MODEL_LIMITS):
        required.update({HookPoint.MODEL_BEFORE, HookPoint.MODEL_AFTER})
    return required


def _middleware_name(item: MiddlewareSpec, duplicates: set[str]) -> str:
    return f"{item.use}[{item.id}]" if item.use in duplicates and item.id else item.use


@dataclass(slots=True)
class _Task:
    name: str
    spec: TaskSpec
    info: TaskInfo
    runner: Runner
    runner_name: str
    resumable: bool


@dataclass(slots=True)
class _Channel:
    """Live subscribers to one run's events."""

    seq: int = 0
    subscribers: list[MemoryObjectSendStream[RunEvent]] = field(
        default_factory=list[MemoryObjectSendStream[RunEvent]]
    )
    closed: bool = False


@dataclass(slots=True)
class _Run:
    """One run being driven by this harness."""

    record: RunRecord
    ctx: RunContext
    task: _Task | None
    input: JsonValue
    channel: _Channel


@dataclass(slots=True)
class _Active:
    scope: anyio.CancelScope
    done: anyio.Event


class Harness:
    """The runtime built from one app's effective spec.

    Build it with :meth:`load` or :meth:`from_spec`. Use ``async with harness:``
    to :meth:`submit` background runs; :meth:`run` and :meth:`session` work
    without it.
    """

    def __init__(
        self,
        effective: EffectiveSpec,
        *,
        registry: Registry,
        bus: HookBus,
        tasks: Mapping[str, _Task],
        models: ModelAccess,
        state: StateStore,
        prompts: PromptStore,
        tools: ToolBackend | None,
        clock: Clock,
        telemetry: Telemetry | None = None,
    ) -> None:
        self._effective = effective
        self._telemetry = telemetry or Telemetry()
        self._registry = registry
        self._bus = bus
        self._tasks = dict(tasks)
        self._models = models
        self._state = state
        self._prompts = prompts
        self._tools = tools
        self._clock = clock
        self._group: TaskGroup | None = None
        self._active: dict[str, _Active] = {}
        self._channels: dict[str, _Channel] = {}

    # --- building ---------------------------------------------------------------------------

    @classmethod
    def load(
        cls,
        path: str | Path,
        *,
        env: str | None = None,
        profile_dirs: Sequence[Path] = (),
        clock: Clock | None = None,
        tools: ToolBackend | None = None,
        catalog: PluginCatalog | None = None,
        telemetry: Telemetry | None = None,
    ) -> Self:
        """Load ``harness.yaml`` (with profiles and overlay) and build the harness.

        Loading is synchronous start-up work: it reads files and imports the
        plugins the spec references.

        Raises:
            SpecError: For anything wrong with the spec, its plugins or its tasks.
        """
        catalog = catalog or PluginCatalog.default()
        effective = load_spec(path, env=env, profile_dirs=profile_dirs, catalog=catalog)
        return cls.from_spec(
            effective, clock=clock, tools=tools, catalog=catalog, telemetry=telemetry
        )

    @classmethod
    def from_spec(
        cls,
        effective: EffectiveSpec,
        *,
        clock: Clock | None = None,
        tools: ToolBackend | None = None,
        catalog: PluginCatalog | None = None,
        telemetry: Telemetry | None = None,
        model: ModelProvider | None = None,
    ) -> Self:
        """Build a harness from an already loaded spec. See :meth:`load`.

        ``telemetry`` replaces the harness's own (for example to use specific
        OpenTelemetry providers); ``observability.capture_content`` still applies.
        ``model`` replaces ``models.provider`` with a provider object, for tests
        and offline runs (``harnessweaver.testing.harness_for_test``); aliases,
        prices and allow-lists still apply.
        """
        spec = effective.spec
        unsupported = _unsupported(spec)
        if unsupported:
            raise SpecError(
                f"{spec.metadata.name} uses {', '.join(unsupported)}, which this release of "
                f"harnessweaver doesn't support yet",
                sections=list[JsonValue](unsupported),
            )
        registry = Registry(
            catalog or PluginCatalog.default(), allow=spec.plugins.allow, local=spec.plugins.local
        )
        base = effective.path.parent if effective.path is not None else Path.cwd()

        state = registry.provider("StateStore", spec.state.use).build(
            spec.state.provider_settings()
        )
        built = cls._build_telemetry(spec, registry)
        if telemetry is not None:
            telemetry.capture_content = spec.observability.capture_content
        telemetry = telemetry or built
        models = cls._model_access(spec, registry, model)
        bus = HookBus()
        install_guardrails(effective, registry, bus)
        install_validation(effective, bus)
        cls._install_middleware(spec, registry, bus)
        prompts = PromptStore(base / spec.prompts.dir)
        tasks = {
            name: cls._build_task(effective, name, task, registry, bus, models, prompts, tools)
            for name, task in spec.tasks.items()
        }
        return cls(
            effective,
            registry=registry,
            bus=bus,
            tasks=tasks,
            models=models,
            state=state,
            prompts=prompts,
            tools=tools,
            clock=clock or SystemClock(),
            telemetry=telemetry,
        )

    @staticmethod
    def _build_telemetry(spec: HarnessSpec, registry: Registry) -> Telemetry:
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

    @staticmethod
    def _model_access(
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

    @staticmethod
    def _install_middleware(spec: HarnessSpec, registry: Registry, bus: HookBus) -> None:
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
                    name=_middleware_name(item, duplicates),
                    handler=declared.build(item.provider_settings()),
                    hooks=frozenset(hooks),
                    band=item.band or declared.band,
                    fail_mode=item.fail_mode or declared.fail_mode,
                    timeout=item.timeout if item.timeout is not None else declared.timeout,
                )
            )

    @staticmethod
    def _build_task(
        effective: EffectiveSpec,
        name: str,
        task: TaskSpec,
        registry: Registry,
        bus: HookBus,
        models: ModelAccess,
        prompts: PromptStore,
        tools: ToolBackend | None,
    ) -> _Task:
        where = f"tasks.{name}"
        info = registry.runner(task.runner.use)
        runner = info.build(task.runner.provider_settings())
        required = _required_hooks(bus, effective.run_budget(name), name)
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
        return _Task(
            name=name,
            spec=task,
            info=TaskInfo(
                name=name,
                version=task.version,
                model=task.model,
                prompt=task.prompt,
                tools=task.tools,
                input_type=_import_type(task.input, f"{where}.input"),
                output_type=_import_type(task.output, f"{where}.output"),
                max_repairs=validation.max_repairs,
                on_failure=validation.on_failure,
            ),
            runner=runner,
            runner_name=info.name,
            resumable=info.resumable,
        )

    # --- introspection ----------------------------------------------------------------------

    @property
    def spec(self) -> EffectiveSpec:
        """The effective spec this harness was built from."""
        return self._effective

    @property
    def name(self) -> str:
        return self._effective.spec.metadata.name

    @property
    def registry(self) -> Registry:
        return self._registry

    @property
    def tasks(self) -> list[str]:
        return sorted(self._tasks)

    def explain(self) -> list[ExplainRow]:
        """Every effective value with its layer, lock and bounds (``spec explain``)."""
        return self._effective.explain()

    def hooks(self, task: str | None = None) -> dict[HookPoint, list[Registration]]:
        """The middleware chain of every hook point, in execution order."""
        return {hook: self._bus.chain(hook, task) for hook in HookPoint}

    # --- lifecycle --------------------------------------------------------------------------

    async def __aenter__(self) -> Self:
        group = anyio.create_task_group()
        await group.__aenter__()
        self._group = group
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        group, self._group = self._group, None
        try:
            if group is not None:
                await group.__aexit__(exc_type, exc, traceback)
        finally:
            await self.aclose()

    async def aclose(self) -> None:
        """Release the state store's resources."""
        await self._state.aclose()

    # --- runs -------------------------------------------------------------------------------

    def _task(self, task: str) -> _Task:
        found = self._tasks.get(task)
        if found is None:
            raise NotFound(f"unknown task {task!r}; tasks: {', '.join(self.tasks)}", task=task)
        return found

    def _context(
        self,
        envelope: Envelope,
        task: TaskInfo | None,
        channel: _Channel,
        *,
        meter: BudgetMeter,
        trace_events: tuple[TraceEvent, ...] = (),
        grants: Sequence[Grant] = (),
        can_suspend: bool = True,
    ) -> RunContext:
        run_id = envelope.run_id

        def on_trace(event: TraceEvent) -> None:
            self._publish(run_id, channel, "trace", trace=event)
            self._telemetry.trace_event(event)

        def on_chunk(chunk: StreamChunk) -> None:
            self._publish(run_id, channel, "chunk", chunk=chunk)

        return RunContext(
            envelope=envelope,
            bus=self._bus,
            trace=RunTrace(self._clock, events=trace_events, on_event=on_trace),
            meter=meter,
            models=self._models,
            tools=self._tools,
            task=task,
            prompts=self._prompts,
            grants=grants,
            on_chunk=on_chunk,
            harness=self,
            can_suspend=can_suspend,
            telemetry=self._telemetry,
        )

    async def _new_run(
        self,
        task: _Task | None,
        task_name: str | None,
        input: Any,
        *,
        principal: Principal | str,
        tenant: str,
        budget: Budget,
        idempotency_key: str | None,
        attributes: Mapping[str, str] | None,
        can_suspend: bool = True,
    ) -> _Run | RunResult:
        run_id = new_id("run")
        if idempotency_key is not None and task_name is not None:
            owner = await self._state.claim_idempotency(tenant, task_name, idempotency_key, run_id)
            if owner != run_id:
                return await self.result(owner)
        envelope = Envelope.new(
            tenant=tenant,
            principal=principal,
            task=task_name,
            task_version=task.spec.version if task is not None else None,
            budget=budget,
            clock=self._clock,
            run_id=run_id,
            idempotency_key=idempotency_key,
            attributes=dict(attributes or {}),
        )
        now = self._clock.now()
        data = to_json(input)
        record = RunRecord(
            run_id=run_id,
            tenant=tenant,
            task=task_name,
            status=RunStatus.PENDING,
            envelope=envelope,
            input=data,
            created_at=now,
            updated_at=now,
        )
        await self._state.put_run(record)
        channel = self._channels.setdefault(run_id, _Channel())
        info = task.info if task is not None else self._session_info(task_name)
        ctx = self._context(
            envelope, info, channel, meter=BudgetMeter(budget), can_suspend=can_suspend
        )
        await self._set_status(run := _Run(record, ctx, task, data, channel), RunStatus.PENDING)
        return run

    def _session_info(self, name: str | None) -> TaskInfo | None:
        if name is None:
            return None
        validation = self._effective.spec.validation
        return TaskInfo(
            name=name, max_repairs=validation.max_repairs, on_failure=validation.on_failure
        )

    async def run(
        self,
        task: str,
        input: Any = None,
        *,
        principal: Principal | str = "anonymous",
        tenant: str = "default",
        idempotency_key: str | None = None,
        budget: Mapping[str, object] | None = None,
        attributes: Mapping[str, str] | None = None,
    ) -> RunResult:
        """Run ``task`` to a terminal state, or until it suspends for approval.

        A repeated ``idempotency_key`` returns the first run's result instead
        of running again (DESIGNS No. 18). ``budget`` may lower the task's
        ``overridable`` limits for this run (R10).

        Raises:
            NotFound: For an unknown task.
            BoundViolation: For a budget override that isn't allowed.
        """
        prepared = await self._prepare(
            task, input, principal, tenant, idempotency_key, budget, attributes
        )
        if isinstance(prepared, RunResult):
            return prepared
        return await self._drive(prepared)

    async def submit(
        self,
        task: str,
        input: Any = None,
        *,
        principal: Principal | str = "anonymous",
        tenant: str = "default",
        idempotency_key: str | None = None,
        budget: Mapping[str, object] | None = None,
        attributes: Mapping[str, str] | None = None,
    ) -> str:
        """Start ``task`` in the background and return its run id at once.

        Needs ``async with harness:``. Follow it with :meth:`stream` and
        :meth:`result`.

        Raises:
            SpecError: Outside ``async with harness:``.
        """
        if self._group is None:
            raise SpecError("submit() needs an open harness: use 'async with harness:'")
        prepared = await self._prepare(
            task, input, principal, tenant, idempotency_key, budget, attributes
        )
        if isinstance(prepared, RunResult):
            return prepared.run_id
        self._active[prepared.ctx.run_id] = _Active(anyio.CancelScope(), anyio.Event())
        self._group.start_soon(self._drive, prepared)
        return prepared.ctx.run_id

    async def _prepare(
        self,
        task: str,
        input: Any,
        principal: Principal | str,
        tenant: str,
        idempotency_key: str | None,
        budget: Mapping[str, object] | None,
        attributes: Mapping[str, str] | None,
    ) -> _Run | RunResult:
        found = self._task(task)
        limits = self._effective.run_budget(task, budget)
        return await self._new_run(
            found,
            task,
            input,
            principal=principal,
            tenant=tenant,
            budget=limits,
            idempotency_key=idempotency_key,
            attributes=attributes,
        )

    async def _drive(
        self,
        run: _Run,
        checkpoint: Checkpoint | None = None,
        answered: tuple[ApprovalRequest, ApprovalDecision] | None = None,
    ) -> RunResult:
        run_id = run.ctx.run_id
        active = self._active.setdefault(run_id, _Active(anyio.CancelScope(), anyio.Event()))
        try:
            result: RunResult | None = None
            try:
                with active.scope:
                    result = await self._execute(run, checkpoint, answered)
            except anyio.get_cancelled_exc_class():
                # The caller was cancelled: record the run as cancelled, then let it go.
                with anyio.CancelScope(shield=True):
                    await self._finish(run, RunStatus.CANCELLED)
                raise
            if result is None:
                result = await self._finish(run, RunStatus.CANCELLED)
            return result
        finally:
            active.done.set()
            self._active.pop(run_id, None)

    async def _execute(
        self,
        run: _Run,
        checkpoint: Checkpoint | None,
        answered: tuple[ApprovalRequest, ApprovalDecision] | None,
    ) -> RunResult:
        with self._telemetry.run_scope(run.ctx.envelope) as span:
            run.ctx.set_trace_id(Telemetry.trace_id(span))
            result = await self._execute_steps(run, checkpoint, answered)
            Telemetry.run_done(span, result)
            return result

    async def _execute_steps(
        self,
        run: _Run,
        checkpoint: Checkpoint | None,
        answered: tuple[ApprovalRequest, ApprovalDecision] | None,
    ) -> RunResult:
        ctx = run.ctx
        with ctx.activate():
            try:
                left = ctx.time_left()
                with anyio.fail_after(left.total_seconds() if left is not None else None):
                    output = await self._steps(run, checkpoint, answered)
            except RunSuspended:
                return await self._suspend(run)
            except RunInterrupted as exc:
                status = RunStatus.BLOCKED if isinstance(exc, RunBlocked) else RunStatus.ESCALATED
                return await self._finish(run, status, error=exc)
            except HarnessError as exc:
                return await self._fail(run, exc)
            except TimeoutError:
                return await self._fail(run, DeadlineExceeded("the run passed its deadline"))
            except Exception as exc:
                _log.warning("run %s failed with %s", ctx.run_id, type(exc).__name__)
                return await self._fail(run, from_known(exc) or classify(exc))
            return await self._finish(run, RunStatus.COMPLETED, output=output)

    async def _steps(
        self,
        run: _Run,
        checkpoint: Checkpoint | None,
        answered: tuple[ApprovalRequest, ApprovalDecision] | None,
    ) -> JsonValue:
        ctx, task = run.ctx, run.task
        assert task is not None
        if checkpoint is None:
            start = await ctx.emit(
                HookPoint.RUN_START, RunStartEvent(task=task.name, input=run.input)
            )
            ctx.halt_on(start)
            await self._set_status(run, RunStatus.RUNNING)
            run.input = await ctx.check_input(run.input)
            ctx.input = run.input
        else:
            ctx.input = run.input
            await self._set_status(run, RunStatus.RUNNING)
            if answered is not None:
                request, decision = answered
                await ctx.approval_resolved(request, decision)
                if decision.decision == "reject":
                    raise RunBlocked(
                        "the approver rejected the step",
                        hook=HookPoint.APPROVAL_RESOLVED.value,
                        code="approval_rejected",
                    )
        value = self._typed_input(task, run.input)
        output = await task.runner.execute(ctx, value, checkpoint.resume if checkpoint else None)
        return to_json(output)

    @staticmethod
    def _typed_input(task: _Task, value: JsonValue) -> Any:
        model = task.info.input_type
        if model is None or model is str:
            return value
        try:
            if issubclass(model, BaseModel):
                return model.model_validate(value)
            return value
        except ValidationError as exc:
            raise from_known(exc) or ValidationFailed("invalid input") from None

    async def _fail(self, run: _Run, error: HarnessError) -> RunResult:
        ctx = run.ctx
        info = error.to_info()
        result = await ctx.emit(
            HookPoint.RUN_ERROR, RunErrorEvent(error=info), check_deadline=False
        )
        if isinstance(result.outcome, Retry):
            ctx.trace.note(
                "harness",
                "Retry at run.error isn't supported; the run fails",
                hook=HookPoint.RUN_ERROR,
            )
        return await self._finish(run, RunStatus.FAILED, error_info=result.event.error)

    async def _finish(
        self,
        run: _Run,
        status: RunStatus,
        *,
        output: JsonValue = None,
        error: HarnessError | None = None,
        error_info: Any = None,
    ) -> RunResult:
        ctx = run.ctx
        info = error.to_info() if error is not None else error_info
        meter = ctx.meter
        end = RunEndEvent(
            status=status,
            output=output,
            error=info,
            usage=meter.usage,
            cost_usd=meter.usd if meter.cost_known or meter.usd else None,
        )
        result = await ctx.emit(HookPoint.RUN_END, end, check_deadline=False)
        if result.halted and status is RunStatus.COMPLETED:
            interrupt = ctx.interrupt(HookPoint.RUN_END, result.outcome)
            status = RunStatus.BLOCKED if isinstance(interrupt, RunBlocked) else RunStatus.ESCALATED
            output, info = None, interrupt.to_info()
        final = self._result(run, status, output=output, error=info)
        await self._store(run, status, final)
        await self._state.delete_checkpoint(ctx.run_id)
        self._close(run.channel)
        return final

    def _result(self, run: _Run, status: RunStatus, **fields: Any) -> RunResult:
        ctx, meter = run.ctx, run.ctx.meter
        return RunResult(
            run_id=ctx.run_id,
            task=run.record.task,
            task_version=run.record.envelope.task_version,
            status=status,
            usage=meter.usage,
            cost_usd=meter.usd if meter.cost_known or meter.usd else None,
            cost_known=meter.cost_known,
            trace=ctx.trace.events,
            started_at=run.record.created_at,
            ended_at=self._clock.now() if status.is_terminal else None,
            **fields,
        )

    async def _store(self, run: _Run, status: RunStatus, result: RunResult) -> None:
        run.record = run.record.model_copy(
            update={"status": status, "result": result, "updated_at": self._clock.now()}
        )
        await self._state.put_run(run.record)
        await self._event(run, "status", status=status)

    async def _set_status(self, run: _Run, status: RunStatus) -> None:
        if status is not run.record.status:
            run.record = run.record.model_copy(
                update={"status": status, "updated_at": self._clock.now()}
            )
            await self._state.put_run(run.record)
        await self._event(run, "status", status=status)

    # --- approvals --------------------------------------------------------------------------

    def _task_approvals(self, run: _Run) -> TaskApprovals:
        if run.task is not None and run.task.spec.approvals is not None:
            return run.task.spec.approvals
        return TaskApprovals()

    def _approver_role(self, run: _Run, role: str | None) -> str | None:
        return (
            role
            or self._task_approvals(run).approver_role
            or self._effective.spec.approvals.approver_role
        )

    def _approval_timeout(self, run: _Run) -> timedelta | None:
        timeout = self._task_approvals(run).timeout
        return timeout if timeout is not None else self._effective.spec.approvals.timeout

    async def _suspend(self, run: _Run) -> RunResult:
        ctx = run.ctx
        pending = ctx.pending
        if pending is None:  # pragma: no cover - RunSuspended always records what it waits on
            return await self._finish(run, RunStatus.ESCALATED)
        now = self._clock.now()
        timeout = self._approval_timeout(run)
        approval = ApprovalRequest(
            approval_id=new_id("apr"),
            run_id=ctx.run_id,
            reason=pending.reason,
            approver_role=self._approver_role(run, pending.approver_role),
            call=pending.call,
            tool=pending.tool,
            requested_at=now,
            expires_at=now + timeout if timeout is not None else None,
        )
        checkpoint = Checkpoint(
            run_id=ctx.run_id,
            task=run.record.task,
            input=run.input,
            resume=ctx.resume_point,
            meter=ctx.meter.snapshot(),
            labels=ctx.envelope.labels,
            grants=tuple(ctx.grants),
            approval=approval,
            approval_hook=pending.hook.value,  # pyright: ignore[reportArgumentType]
            approval_digest=pending.digest,
            time_left=ctx.time_left(),
        )
        await self._state.put_checkpoint(checkpoint)
        self._telemetry.approval(ctx.run_id, approval.approval_id, "requested")
        ctx.trace.note(
            "harness.approvals",
            pending.reason,
            hook=pending.hook,
            details={"approval_id": approval.approval_id},
        )
        result = self._result(run, RunStatus.AWAITING_APPROVAL, approval=approval)
        await self._store(run, RunStatus.AWAITING_APPROVAL, result)
        await self._event(run, "approval", approval=approval)
        self._close(run.channel)
        return result

    async def _restore(self, record: RunRecord, checkpoint: Checkpoint) -> _Run:
        task = self._task(record.task) if record.task is not None else None
        envelope = record.envelope.with_clock(self._clock)
        deadline = (
            self._clock.now() + checkpoint.time_left if checkpoint.time_left is not None else None
        )
        envelope = envelope.model_copy(update={"labels": checkpoint.labels, "deadline": deadline})
        channel = self._channels.setdefault(record.run_id, _Channel())
        channel.closed = False
        channel.seq = max([e.seq for e in await self._state.events(record.run_id)], default=-1) + 1
        previous = record.result.trace if record.result is not None else ()
        ctx = self._context(
            envelope,
            task.info if task is not None else None,
            channel,
            meter=BudgetMeter.restore(record.envelope.budget, checkpoint.meter),
            trace_events=previous,
            grants=checkpoint.grants,
        )
        return _Run(record, ctx, task, checkpoint.input, channel)

    async def approve(
        self,
        run_id: str,
        approval_id: str,
        decision: ApprovalAnswer = "approve",
        *,
        approver: Principal | str,
        edited_args: dict[str, JsonValue] | None = None,
        reason: str | None = None,
    ) -> RunResult:
        """Answer a pending approval and continue the run (DESIGNS No. 18).

        1. Checks the approver holds the request's ``approver_role``.
        2. Fires ``approval.resolved``.
        3. On ``approve`` or ``edit``, resumes; edited arguments go through
           ``tool.before`` again. On ``reject``, the run ends ``blocked``.

        An expired request ends the run as ``approvals.on_timeout`` says.

        Raises:
            NotFound: If the run has no such pending approval.
            PolicyDenied: If the approver lacks the required role.
            ValidationFailed: For an ``edit`` without arguments, or of an output.
        """
        record = await self._state.get_run(run_id)
        checkpoint = await self._state.get_checkpoint(run_id)
        if (
            record is None
            or record.status is not RunStatus.AWAITING_APPROVAL
            or checkpoint is None
            or checkpoint.approval is None
            or checkpoint.approval.approval_id != approval_id
        ):
            raise NotFound(f"run {run_id} has no pending approval {approval_id!r}", run_id=run_id)
        request = checkpoint.approval
        who = approver if isinstance(approver, Principal) else Principal(id=approver)
        if request.approver_role is not None and not who.has_role(request.approver_role):
            raise PolicyDenied(
                f"approving needs the role {request.approver_role!r}", approval_id=approval_id
            )
        try:
            answer = ApprovalDecision(
                approval_id=approval_id,
                decision=decision,
                approver=who,
                edited_args=edited_args,
                reason=reason,
            )
        except ValidationError as exc:
            raise from_known(exc) or ValidationFailed("invalid approval") from None
        if answer.decision == "edit" and checkpoint.approval_hook != HookPoint.TOOL_BEFORE.value:
            raise ValidationFailed("only a tool call's arguments can be edited")
        run = await self._restore(record, checkpoint)
        self._telemetry.approval(run_id, approval_id, answer.decision)
        if request.expires_at is not None and self._clock.now() > request.expires_at:
            return await self._expire(run)
        grants = list(checkpoint.grants)
        if answer.decision != "reject" and checkpoint.approval_hook and checkpoint.approval_digest:
            grants.append(
                Grant(
                    hook=checkpoint.approval_hook,
                    digest=checkpoint.approval_digest,
                    decision=answer,
                )
            )
        run.ctx.grants = grants
        # Persist the answer before resuming, so a crash doesn't lose it (resume() continues).
        resolved = checkpoint.model_copy(update={"approval": None, "grants": tuple(grants)})
        await self._state.put_checkpoint(resolved)
        return await self._drive(run, resolved, (request, answer))

    async def _expire(self, run: _Run) -> RunResult:
        on_timeout = (
            self._task_approvals(run).on_timeout or self._effective.spec.approvals.on_timeout
        )
        reason = "the approval request expired"
        run.ctx.trace.note("harness.approvals", reason, code="approval_timeout")
        if on_timeout == "reject":
            return await self._finish(
                run, RunStatus.BLOCKED, error=RunBlocked(reason, code="approval_timeout")
            )
        return await self._finish(
            run, RunStatus.ESCALATED, error=RunEscalated(reason, code="approval_timeout")
        )

    async def resume(self, run_id: str) -> RunResult:
        """Continue a run whose approval was answered but which didn't finish (a crash).

        Raises:
            NotFound: If the run has nothing to resume, or is still waiting for approval.
        """
        record = await self._state.get_run(run_id)
        checkpoint = await self._state.get_checkpoint(run_id)
        if record is None or checkpoint is None or record.status.is_terminal:
            raise NotFound(f"run {run_id} has nothing to resume", run_id=run_id)
        if checkpoint.approval is not None:
            raise NotFound(f"run {run_id} is still waiting for approval", run_id=run_id)
        if run_id in self._active:
            raise NotFound(f"run {run_id} is already running here", run_id=run_id)
        return await self._drive(await self._restore(record, checkpoint), checkpoint)

    async def cancel(self, run_id: str) -> RunResult:
        """Cancel a run that is running here or waiting for approval.

        A finished run is returned unchanged.

        Raises:
            NotFound: For an unknown run.
        """
        active = self._active.get(run_id)
        if active is not None:
            active.scope.cancel()
            await active.done.wait()
            return await self.result(run_id)
        record = await self._state.get_run(run_id)
        if record is None:
            raise NotFound(f"no run {run_id}", run_id=run_id)
        if record.status.is_terminal and record.result is not None:
            return record.result
        checkpoint = await self._state.get_checkpoint(run_id) or Checkpoint(run_id=run_id)
        run = await self._restore(record, checkpoint)
        return await self._finish(run, RunStatus.CANCELLED)

    async def result(self, run_id: str) -> RunResult:
        """The latest state of a run.

        Raises:
            NotFound: For an unknown run.
        """
        record = await self._state.get_run(run_id)
        if record is None:
            raise NotFound(f"no run {run_id}", run_id=run_id)
        if record.result is not None:
            return record.result
        return RunResult(
            run_id=run_id,
            task=record.task,
            task_version=record.envelope.task_version,
            status=record.status,
            started_at=record.created_at,
        )

    # --- events -----------------------------------------------------------------------------

    def _publish(self, run_id: str, channel: _Channel, type_: str, **fields: Any) -> RunEvent:
        event = RunEvent.model_validate(
            {"run_id": run_id, "seq": channel.seq, "at": self._clock.now(), "type": type_, **fields}
        )
        channel.seq += 1
        for subscriber in list(channel.subscribers):
            try:
                subscriber.send_nowait(event)
            except (anyio.BrokenResourceError, anyio.ClosedResourceError):
                channel.subscribers.remove(subscriber)
        return event

    async def _event(self, run: _Run, type_: str, **fields: Any) -> None:
        event = self._publish(run.ctx.run_id, run.channel, type_, **fields)
        await self._state.append_event(event)

    def _close(self, channel: _Channel) -> None:
        channel.closed = True
        for subscriber in channel.subscribers:
            subscriber.close()
        channel.subscribers.clear()

    async def stream(self, run_id: str) -> AsyncIterator[RunEvent]:
        """Yield a run's events: its stored history, then live events until it stops.

        ``status`` and ``approval`` events come from the state store; ``trace`` and
        ``chunk`` events are only seen while the run is live in this process.
        """
        channel = self._channels.get(run_id)
        if channel is None or channel.closed:
            for event in await self._state.events(run_id):
                yield event
            return
        send, receive = anyio.create_memory_object_stream[RunEvent](math.inf)
        channel.subscribers.append(send)
        seen: set[int] = set()
        for event in await self._state.events(run_id):
            seen.add(event.seq)
            yield event
        async with receive:
            async for event in receive:
                if event.type in ("status", "approval") and event.seq in seen:
                    continue
                yield event

    # --- wrap style -------------------------------------------------------------------------

    def instrument[T](
        self,
        client: T,
        *,
        task: str | None = None,
        principal: Principal | str = "anonymous",
        tenant: str = "default",
        attributes: Mapping[str, str] | None = None,
        adapter: str | None = None,
    ) -> T:
        """Return a governed version of ``client`` (DESIGNS No. 15, L0).

        The adapter is found from the client's type: the plugin whose namespace
        is the client's top-level package (``openai``, ``anthropic``) is loaded
        and asked for an adapter that wraps the type. Name one with ``adapter``.

        Raises:
            UnknownProvider: If no installed plugin wraps the client's type.
            PluginNotAllowed: If that plugin isn't in ``plugins.allow``.
            UnreachableHook: If the adapter can't reach a hook the baseline or
                the budgets need (R4).
        """
        info = self._adapter_for(client, adapter)
        if task is not None and task in self._tasks:
            budget = self._effective.run_budget(task)
        else:
            budget = self._effective.spec.budgets.per_run
        missing = sorted(h.value for h in _required_hooks(self._bus, budget, task) - info.reaches)
        if missing:
            raise UnreachableHook(
                f"adapter {info.name} can't reach {', '.join(missing)}, which the baseline "
                f"needs (RULES R4)",
                hooks=list[JsonValue](missing),
            )
        binding = Binding(self, task, principal, tenant, dict(attributes or {}))
        return info.target().bind(client, binding)

    def _adapter_for(self, target: object, name: str | None) -> AdapterInfo:
        if name is not None:
            return self._registry.adapter(name)
        kind = type(target)
        for cls in kind.__mro__:
            root = cls.__module__.split(".", 1)[0]
            if root == "builtins":
                continue
            try:
                self._registry.ensure(root)
            except UnknownProvider:
                continue
            names = {f"{root}.{cls.__name__}", f"{cls.__module__}.{cls.__qualname__}"}
            for info in self._registry.adapters():
                if names & set(info.wraps):
                    return info
        raise UnknownProvider(
            f"no installed plugin has an adapter for {kind.__module__}.{kind.__qualname__}",
            type=f"{kind.__module__}.{kind.__qualname__}",
        )

    # --- sessions ---------------------------------------------------------------------------

    def session(
        self,
        task: str | None = None,
        *,
        principal: Principal | str = "anonymous",
        tenant: str = "default",
        budget: Budget | None = None,
        attributes: Mapping[str, str] | None = None,
    ) -> Session:
        """Open a governed session: ``async with harness.session(...) as s:`` (DESIGNS No. 15).

        A session is a run whose flow the app owns. Its budget is the spec's
        ``budgets.per_run``, tightened by ``budget`` and by the task's own limits
        when ``task`` names a task in the spec. ``Suspend`` escalates here,
        because the app's code can't be resumed later.
        """
        limits = self._effective.spec.budgets.per_run
        if task is not None and task in self._tasks:
            limits = self._effective.run_budget(task)
        if budget is not None:
            limits = limits.intersect(budget)
        pending = _PendingSession(task, principal, tenant, limits, attributes)
        return Session(None, harness=self, pending=pending)

    async def _open_session(self, pending: "_PendingSession") -> RunContext:
        task = self._tasks.get(pending.task) if pending.task is not None else None
        run = await self._new_run(
            task,
            pending.task,
            None,
            principal=pending.principal,
            tenant=pending.tenant,
            budget=pending.budget,
            idempotency_key=None,
            attributes=pending.attributes,
            can_suspend=False,
        )
        assert isinstance(run, _Run)
        pending.run = run
        stack = contextlib.ExitStack()
        span = stack.enter_context(self._telemetry.run_scope(run.ctx.envelope))
        run.ctx.set_trace_id(Telemetry.trace_id(span))
        stack.enter_context(run.ctx.activate())
        pending.stack, pending.span = stack, span
        start = await run.ctx.emit(HookPoint.RUN_START, RunStartEvent(task=pending.task))
        try:
            run.ctx.halt_on(start)
        except RunInterrupted as exc:
            await self._close_session(pending, exc)
            raise
        await self._set_status(run, RunStatus.RUNNING)
        return run.ctx

    async def _close_session(
        self, pending: "_PendingSession", exc: BaseException | None
    ) -> RunResult:
        run = pending.run
        assert run is not None
        if pending.result is not None:
            return pending.result
        result: RunResult | None = None
        try:
            with anyio.CancelScope(shield=True):
                if exc is None:
                    result = await self._finish(run, RunStatus.COMPLETED, output=run.ctx.output)
                elif isinstance(exc, RunBlocked):
                    result = await self._finish(run, RunStatus.BLOCKED, error=exc)
                elif isinstance(exc, RunInterrupted):
                    result = await self._finish(run, RunStatus.ESCALATED, error=exc)
                elif isinstance(exc, Exception):
                    error = exc if isinstance(exc, HarnessError) else classify(exc)
                    result = await self._fail(run, error)
                else:
                    result = await self._finish(run, RunStatus.CANCELLED)
        finally:
            if result is not None and pending.span is not None:
                Telemetry.run_done(pending.span, result)
            if pending.stack is not None:
                pending.stack.close()
                pending.stack = None
        assert result is not None
        pending.result = result
        return result


@dataclass(slots=True)
class _PendingSession:
    """A ``harness.session(...)`` call, before and after its run exists."""

    task: str | None
    principal: Principal | str
    tenant: str
    budget: Budget
    attributes: Mapping[str, str] | None
    run: _Run | None = None
    stack: contextlib.ExitStack | None = None
    span: Span | None = None
    result: RunResult | None = None
