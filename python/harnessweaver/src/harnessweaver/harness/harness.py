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

from collections.abc import Mapping, Sequence
from pathlib import Path
from types import TracebackType
from typing import Self

import anyio
from pydantic import JsonValue

from harnessweaver.adapters import Binding
from harnessweaver.core.bus import HookBus
from harnessweaver.core.envelope import Budget, Clock, Principal, SystemClock
from harnessweaver.core.errors import (
    UnreachableHook,
)
from harnessweaver.core.evals import EvalDataset, SuiteResult
from harnessweaver.core.ports import ModelProvider, StateStore, ToolBackend
from harnessweaver.core.registry import PluginCatalog, Registry
from harnessweaver.core.telemetry import Telemetry
from harnessweaver.harness.build import (
    build_task,
    build_telemetry,
    check_telemetry,
    install_middleware,
    model_access,
    output_schema,
    required_hooks,
)
from harnessweaver.harness.governance import (
    build_channel,
    build_context,
    build_governor,
    build_memory,
    build_policy,
    build_tools,
)
from harnessweaver.harness.records import PendingSession
from harnessweaver.harness.replay import ReplayMixin
from harnessweaver.modules.evals import install_online_evals, load_dataset, run_suite
from harnessweaver.modules.guardrails import install_guardrails
from harnessweaver.modules.prompts import PromptStore
from harnessweaver.modules.routing import install_routing
from harnessweaver.modules.validation import install_validation
from harnessweaver.session import Session
from harnessweaver.spec.loader import EffectiveSpec, load_spec

__all__ = ["Harness"]


class Harness(ReplayMixin):
    """The runtime built from one app's effective spec.

    Build it with :meth:`load` or :meth:`from_spec`. Use ``async with harness:``
    to :meth:`submit` background runs; :meth:`run` and :meth:`session` work
    without it.
    """

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
        state: StateStore | None = None,
    ) -> Self:
        """Build a harness from an already loaded spec. See :meth:`load`.

        ``telemetry`` replaces the harness's own (for example to use specific
        OpenTelemetry providers); ``observability.capture_content`` still applies,
        and the harness then configures no OpenTelemetry SDK itself.
        ``model`` replaces ``models.provider`` with a provider object, for tests
        and offline runs (``harnessweaver.testing.harness_for_test``); aliases,
        prices and allow-lists still apply. ``state`` replaces ``state.use`` with
        a store object, as ``harnessweaver eval run`` does to keep eval runs out
        of the app's store.
        """
        spec = effective.spec
        registry = Registry(
            catalog or PluginCatalog.default(), allow=spec.plugins.allow, local=spec.plugins.local
        )
        base = effective.path.parent if effective.path is not None else Path.cwd()

        store: StateStore = state or registry.provider("StateStore", spec.state.use).build(
            spec.state.provider_settings()
        )
        if telemetry is None:
            telemetry = build_telemetry(spec, registry)
        else:
            check_telemetry(spec)
            telemetry.capture_content = spec.observability.capture_content
        models = model_access(spec, registry, model)
        bus = HookBus()
        install_guardrails(effective, registry, bus)
        install_validation(effective, bus)
        install_middleware(spec, registry, bus)
        install_routing(effective, registry, bus, base)
        prompts = PromptStore(base / spec.prompts.dir)
        policy = build_policy(spec, registry)
        tools, manifests = build_tools(spec, registry, base, tools)
        governor = build_governor(spec, registry, policy, manifests)
        approvals = build_channel(spec, registry)
        context = build_context(spec, registry, base)
        memory = build_memory(spec, registry)
        tasks = {
            name: build_task(effective, name, task, registry, bus, models, prompts, tools)
            for name, task in spec.tasks.items()
        }
        schemas = {name: output_schema(entry.info.output_type) for name, entry in tasks.items()}
        install_online_evals(spec, registry, bus, store, schemas)
        return cls(
            effective,
            registry=registry,
            bus=bus,
            tasks=tasks,
            models=models,
            state=store,
            prompts=prompts,
            tools=tools,
            clock=clock or SystemClock(),
            telemetry=telemetry,
            governor=governor,
            policy=policy,
            approvals=approvals,
            context=context,
            memory=memory,
        )

    def _rebuilt(self, *, model: ModelProvider, state: StateStore, telemetry: Telemetry) -> Self:
        return type(self).from_spec(
            self._effective,
            clock=self._clock,
            tools=self._tools,
            catalog=self._registry.catalog,
            telemetry=telemetry,
            model=model,
            state=state,
        )

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
        return self._bind(client, task, principal, tenant, attributes, adapter)

    def wrap[T](
        self,
        agent: T,
        *,
        task: str | None = None,
        principal: Principal | str = "anonymous",
        tenant: str = "default",
        attributes: Mapping[str, str] | None = None,
        adapter: str | None = None,
    ) -> T:
        """Return a governed version of an agent from another framework (DESIGNS No. 15).

        ``agent = harness.wrap(my_pydantic_agent, task="support_agent")``: the
        adapter is found from the agent's type as :meth:`instrument` finds one, and
        each run of the returned agent is governed: a run of its own, or part of
        the harness run or session it runs inside. ``task`` names the task whose
        budget and middleware apply.

        Raises:
            UnknownProvider: If no installed plugin wraps the agent's type.
            PluginNotAllowed: If that plugin isn't in ``plugins.allow``.
            UnreachableHook: If the adapter can't reach a hook the baseline or
                the budgets need (R4).
        """
        return self._bind(agent, task, principal, tenant, attributes, adapter)

    def _bind[T](
        self,
        target: T,
        task: str | None,
        principal: Principal | str,
        tenant: str,
        attributes: Mapping[str, str] | None,
        adapter: str | None,
    ) -> T:
        info = self._adapter_for(target, adapter)
        if task is not None and task in self._tasks:
            budget = self._effective.run_budget(task)
        else:
            budget = self._effective.spec.budgets.per_run
        missing = sorted(h.value for h in required_hooks(self._bus, budget, task) - info.reaches)
        if missing:
            raise UnreachableHook(
                f"adapter {info.name} can't reach {', '.join(missing)}, which the baseline "
                f"needs (RULES R4)",
                hooks=list[JsonValue](missing),
            )
        binding = Binding(self, task, principal, tenant, dict(attributes or {}))
        return info.target().bind(target, binding)

    async def evaluate(self, dataset: EvalDataset | str | Path) -> SuiteResult:
        """Run an eval suite: each case's task run, graded (DESIGNS No. 23).

        A dataset path is read relative to the spec's directory. Judges grade
        inside a session, so their model calls are governed and budgeted.
        ``harnessweaver eval run`` adds baselines and the shadow-guard report.

        Raises:
            SpecError: For a dataset that isn't valid, or graders that can't be built.
            NotFound: For a task the spec doesn't define.
        """
        if not isinstance(dataset, EvalDataset):
            path = Path(dataset)
            if not path.is_absolute() and self._effective.path is not None:
                path = self._effective.path.parent / path
            dataset = load_dataset(path)
        return await run_suite(self, dataset)

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
        pending = PendingSession(task, principal, tenant, limits, attributes)
        return Session(None, harness=self, pending=pending)
