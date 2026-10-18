"""The conformance checks every plugin contribution must pass (RULES T5).

``pytest --harnessweaver-conformance=<namespace>`` runs them as tests (see
``harnessweaver.testing.conformance_suite``). They are plain async functions
that raise ``AssertionError``, so they also run outside pytest.

| Check | Applies to |
| --- | --- |
| The plugin's metadata, names, contract range, profiles and templates | the plugin |
| Importing the plugin does no I/O and changes no global state (S8) | the plugin |
| Builds from its config (or its ``sample`` settings) | every contribution |
| Results validate against the contract | guardrails, deciders, model providers, state stores |
| Fresh instances repeat their results | deterministic providers |
| A guard that times out blocks when it fails closed | guardrails |
| No raw content reaches logs, spans or traces (R9) | guardrails, model providers |
| p95 latency within the declared ``latency_class`` | guards, deciders, offline models, stores |
| Answers every declared hook with an outcome | middleware |
| A task runs, firing only hooks the runner declares (R4) | runners |
| A call fires the declared hooks, in lifecycle order (R4) | adapters (needs ``sample``) |

Live model providers must refuse the network in test mode (R14).
"""

import logging
import subprocess
import sys
import tempfile
import textwrap
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import timedelta
from importlib.metadata import entry_points
from typing import Any, Final

import anyio

from harnessweaver.core.bus import HookBus
from harnessweaver.core.decisions import Decision
from harnessweaver.core.envelope import Envelope, FakeClock
from harnessweaver.core.errors import ProviderError, RunInterrupted
from harnessweaver.core.guards import GuardAction, GuardResult
from harnessweaver.core.hooks import Band, HookPoint
from harnessweaver.core.messages import ModelResponse, StreamChunk
from harnessweaver.core.middleware import MiddlewareDef, Registration
from harnessweaver.core.outcomes import Block, Continue, Escalate, Retry, Suspend
from harnessweaver.core.plugins import (
    CONTRACT_VERSION,
    ENTRY_POINT_GROUP,
    AdapterInfo,
    Contribution,
    Plugin,
    ProviderInfo,
    RunnerInfo,
    check_owned,
)
from harnessweaver.core.ports import StreamingModelProvider
from harnessweaver.core.registry import LoadedPlugin, PluginCatalog, PluginSource, import_target
from harnessweaver.core.results import RunEvent
from harnessweaver.core.runs import RunStatus
from harnessweaver.core.state import Checkpoint, RunRecord
from harnessweaver.core.telemetry import Telemetry
from harnessweaver.modules.guardrails import Guard, guard_handler
from harnessweaver.spec.yaml import load_yaml
from harnessweaver.testing.kit import harness_for_test, output, scripted
from harnessweaver.testing.samples import (
    CANARY,
    SAMPLE_TEXTS,
    AdapterSample,
    sample_decision_request,
    sample_event,
    sample_request,
)
from harnessweaver.testing.traces import assert_no_content, hooks_fired

__all__ = [
    "LATENCY_LIMITS",
    "LIFECYCLE",
    "Subject",
    "check_adapter",
    "check_builds",
    "check_deterministic",
    "check_import_is_inert",
    "check_latency",
    "check_middleware",
    "check_no_raw_content",
    "check_plugin",
    "check_results",
    "check_runner",
    "check_timeout_blocks",
    "load_plugin",
    "subjects",
]

LATENCY_LIMITS: Final = {"fast": 0.025, "medium": 0.25, "slow": 5.0}
"""p95 seconds allowed per declared latency class."""

LIFECYCLE: Final = (
    HookPoint.RUN_START,
    HookPoint.INPUT_BEFORE,
    HookPoint.ROUTE_DECIDE,
    HookPoint.CONTEXT_AFTER,
    HookPoint.MODEL_BEFORE,
    HookPoint.STREAM_CHUNK,
    HookPoint.MODEL_AFTER,
    HookPoint.TOOL_BEFORE,
    HookPoint.TOOL_AFTER,
    HookPoint.OUTPUT_BEFORE,
    HookPoint.APPROVAL_RESOLVED,
    HookPoint.RUN_ERROR,
    HookPoint.RUN_END,
)
"""The order hook points first fire in during one run."""

_CONDITIONAL: Final = frozenset(
    {
        HookPoint.RUN_ERROR,
        HookPoint.APPROVAL_RESOLVED,
        HookPoint.STREAM_CHUNK,
        HookPoint.ROUTE_DECIDE,
        HookPoint.CONTEXT_AFTER,
        HookPoint.TOOL_BEFORE,
        HookPoint.TOOL_AFTER,
    }
)
"""Hooks that fire only when something specific happens, so one sample call needn't fire them."""


def _expect(condition: object, message: str = "conformance check failed") -> None:
    """Fail a check. Unlike ``assert``, this still runs under ``python -O``."""
    if not condition:
        raise AssertionError(message)


def _env() -> Envelope:
    return Envelope.new(tenant="conformance", principal="tester", clock=FakeClock())


@dataclass(frozen=True, slots=True)
class Subject:
    """One contribution to check, and the plugin it comes from."""

    plugin: LoadedPlugin
    contribution: Contribution

    @property
    def name(self) -> str:
        return self.contribution.name

    @property
    def item(self) -> Any:
        return self.contribution.item

    def spec(self, **sections: Any) -> dict[str, Any]:
        """A spec document that can resolve this plugin's names."""
        document = dict(sections)
        if self.plugin.source.origin == "local":
            document["plugins"] = {"local": [self.plugin.source.target]}
        return document


# --- loading -------------------------------------------------------------------------------------


def load_plugin(selector: str, catalog: PluginCatalog | None = None) -> LoadedPlugin:
    """The plugin to check: an installed namespace, ``harnessweaver`` for the built-in
    plugin, or ``module:attribute`` for an in-repo plugin."""
    if ":" in selector:
        value = import_target(selector)
        if not isinstance(value, Plugin):
            raise AssertionError(f"{selector} is not a harnessweaver.Plugin")
        return LoadedPlugin(value, PluginSource(value.namespace, selector, "local"))
    return (catalog or PluginCatalog.discover()).load(selector)


# --- the plugin ----------------------------------------------------------------------------------


def check_plugin(loaded: LoadedPlugin) -> None:
    """Metadata, names, contract range, profiles and templates."""
    plugin = loaded.plugin
    _expect(
        plugin.contract_range.contains(CONTRACT_VERSION),
        f"contract range {plugin.contract} doesn't include {CONTRACT_VERSION} (V5)",
    )
    if loaded.source.origin == "entry_point":
        points = [ep for ep in entry_points(group=ENTRY_POINT_GROUP) if ep.name == plugin.namespace]
        _expect(points, f"no {ENTRY_POINT_GROUP} entry point named {plugin.namespace!r}")
    seen: set[tuple[str, str]] = set()
    for item in plugin.contributions():
        problem = check_owned(plugin, item)
        if problem is not None:
            raise AssertionError(problem)
        _expect(item.key not in seen, f"{item.name} is contributed twice")
        seen.add(item.key)
        if item.contract is not None:
            _expect(
                item.contract.contains(CONTRACT_VERSION), f"{item.name}: contract {item.contract}"
            )
    for name, path in plugin.profiles.items():
        resource = loaded.resource(path)
        _expect(resource.is_file(), f"profile {name}: {path} doesn't exist")
        document = load_yaml(resource.read_text(encoding="utf-8"), f"profile {name}")
        _expect(isinstance(document, dict), f"profile {name} isn't a map")
        _expect(document.get("kind") == "Profile", f"profile {name} isn't a kind: Profile document")
    for name, path in plugin.templates.items():
        _expect(
            loaded.resource(path).is_dir() or loaded.resource(path).is_file(),
            f"template {name}: {path} doesn't exist",
        )


_INERT_SCRIPT: Final = textwrap.dedent(
    """
    import importlib, os, socket, sys
    def refuse(*args, **kwargs):
        raise RuntimeError("network access at import time")
    socket.socket.connect = refuse
    socket.create_connection = refuse
    before = sorted(os.listdir("."))
    importlib.import_module(sys.argv[1])
    after = sorted(os.listdir("."))
    from opentelemetry import metrics, trace
    problems = []
    if before != after:
        problems.append("files created in the working directory")
    if not isinstance(trace.get_tracer_provider(), trace.ProxyTracerProvider):
        problems.append("a global tracer provider was installed")
    if type(metrics.get_meter_provider()).__name__ != "_ProxyMeterProvider":
        problems.append("a global meter provider was installed")
    print("|".join(problems) or "ok")
    """
)


def check_import_is_inert(module: str) -> None:
    """Importing a plugin opens no sockets, writes no files and installs nothing global (S8)."""
    with tempfile.TemporaryDirectory() as directory:
        done = subprocess.run(
            [sys.executable, "-c", _INERT_SCRIPT, module],
            capture_output=True,
            text=True,
            cwd=directory,
            check=False,
            timeout=60,
        )
    _expect(done.returncode == 0, f"importing {module} failed: {done.stderr.strip()[-500:]}")
    _expect(done.stdout.strip() == "ok", f"importing {module}: {done.stdout.strip()}")
    _expect(not done.stdout.strip().count("\n"), f"importing {module} printed output")


# --- building ------------------------------------------------------------------------------------


def _settings(sample: Any) -> dict[str, Any]:
    return dict(sample) if sample is not None else {}


def build(contribution: Contribution) -> Any:
    """A ready instance of a contribution, from its ``sample`` settings or defaults."""
    item = contribution.item
    if isinstance(item, ProviderInfo):
        return item.build(_settings(item.sample))
    if isinstance(item, MiddlewareDef):
        return item.build(_settings(item.sample) if item.is_class else None)
    if isinstance(item, RunnerInfo):
        return item.build(_settings(item.sample))
    return item.target()


def check_builds(subject: Subject) -> None:
    """Builds from its config model alone, or from its declared ``sample`` (C11)."""
    try:
        built = build(subject.contribution)
    except Exception as exc:
        where = "its sample" if getattr(subject.item, "sample", None) else "defaults"
        raise AssertionError(
            f"{subject.name} doesn't build from {where} ({type(exc).__name__}: {exc}); "
            "declare sample= settings"
        ) from exc
    _expect(built is not None, f"{subject.name} built to None")
    if isinstance(subject.item, AdapterInfo):
        _expect(callable(getattr(built, "bind", None)), f"adapter {subject.name} has no bind()")


# --- results -------------------------------------------------------------------------------------


@contextmanager
def _session_run() -> Iterator[Any]:
    """A harness whose scripted model also answers ``llm.judge``-style questions."""
    yield harness_for_test({}, model=scripted(output({"pass": True, "reason": "fine"})))


async def _guard_results(provider: Any) -> list[GuardResult]:
    with _session_run() as harness:
        async with harness.session() as session:
            return [await provider.check(text, session.envelope) for text in SAMPLE_TEXTS]


async def _model_results(provider: Any) -> list[ModelResponse] | None:
    """Two calls (one streamed, if supported), or ``None`` if the provider refused the
    network as live providers must in test mode."""
    try:
        results = [await provider.generate(sample_request(), _env())]
        if isinstance(provider, StreamingModelProvider):
            items = [item async for item in provider.stream(sample_request(), _env())]
            _expect(items, "stream yielded nothing")
            _expect(
                isinstance(items[-1], ModelResponse), "a stream must end with the ModelResponse"
            )
            _expect(
                all(isinstance(i, StreamChunk) for i in items[:-1]),
                "a stream yields StreamChunks first",
            )
            results.append(items[-1])
    except ProviderError as exc:
        _expect(CANARY not in exc.message)
        return None
    return results


async def _state_contract(store: Any) -> None:
    from harnessweaver.core.envelope import Envelope as _Envelope

    now = FakeClock().now()
    envelope = _Envelope.new(tenant="t", principal="p", run_id="run_conformance")
    record = RunRecord(
        run_id="run_conformance",
        tenant="t",
        task="x",
        status=RunStatus.PENDING,
        envelope=envelope,
        created_at=now,
        updated_at=now,
    )
    await store.put_run(record)
    found = await store.get_run("run_conformance")
    _expect(found is not None and found.run_id == "run_conformance", "put_run/get_run round trip")
    _expect(await store.get_run("run_missing") is None)
    await store.put_checkpoint(Checkpoint(run_id="run_conformance", resume={"step": 1}))
    checkpoint = await store.get_checkpoint("run_conformance")
    _expect(checkpoint is not None and checkpoint.resume == {"step": 1}, "checkpoint round trip")
    await store.delete_checkpoint("run_conformance")
    _expect(await store.get_checkpoint("run_conformance") is None)
    _expect(await store.claim_idempotency("t", "x", "k", "run_a") == "run_a")
    _expect(await store.claim_idempotency("t", "x", "k", "run_b") == "run_a", "idempotency claim")
    for seq in (2, 0, 1):
        await store.append_event(RunEvent(run_id="run_conformance", seq=seq, at=now, type="status"))
    _expect(
        [e.seq for e in await store.events("run_conformance")] == [0, 1, 2], "events in seq order"
    )
    await store.aclose()


async def check_results(subject: Subject) -> None:
    """Results validate against the contract for the provider's port."""
    item = subject.item
    if not isinstance(item, ProviderInfo):
        return
    provider = build(subject.contribution)
    if item.port == "Guardrail":
        for result in await _guard_results(provider):
            _expect(
                isinstance(result, GuardResult), f"{item.name} returned {type(result).__name__}"
            )
            GuardResult.model_validate(result.model_dump())
            if result.action is GuardAction.REDACT:
                _expect(result.content is not None, "a redact result needs content")
            for finding in result.findings:
                _expect(CANARY not in finding.type, "findings must not hold raw content (R9)")
    elif item.port == "Decider":
        decision = await provider(sample_decision_request())
        _expect(isinstance(decision, Decision), f"{item.name} returned {type(decision).__name__}")
        if decision.choice is not None:
            _expect(
                decision.choice in sample_decision_request().options,
                "a choice must be one of the options",
            )
    elif item.port == "ModelProvider":
        for response in await _model_results(provider) or []:
            ModelResponse.model_validate(response.model_dump())
    elif item.port == "StateStore":
        await _state_contract(provider)
    elif item.port == "Telemetry":
        _expect(
            callable(getattr(provider, "configure", None)), "a Telemetry setup needs configure()"
        )


async def check_deterministic(subject: Subject) -> None:
    """Fresh instances of a deterministic provider give the same results for the same input."""
    item = subject.item
    if not isinstance(item, ProviderInfo) or not item.deterministic:
        return
    if item.port == "Guardrail":
        first, second = (
            await _guard_results(build(subject.contribution)),
            await _guard_results(build(subject.contribution)),
        )
        _expect(first == second, f"{item.name} answered differently the second time")
    elif item.port == "Decider":
        _expect(
            await build(subject.contribution)(sample_decision_request())
            == await build(subject.contribution)(sample_decision_request())
        )
    elif item.port == "ModelProvider":
        first_model = await _model_results(build(subject.contribution))
        second_model = await _model_results(build(subject.contribution))
        _expect(first_model == second_model, f"{item.name} answered differently the second time")


class _Slow:
    def __init__(self, inner: Any) -> None:
        self.inner = inner

    async def check(self, content: str, env: Envelope) -> GuardResult:
        result = await self.inner.check(content, env)
        await anyio.sleep(1)
        return result


async def check_timeout_blocks(subject: Subject) -> None:
    """A guard that runs past its timeout blocks when it fails closed, and is cancellable."""
    item = subject.item
    if not isinstance(item, ProviderInfo) or item.port != "Guardrail":
        return
    stage = item.stages[0] if item.stages else "input"
    hook = {
        "input": HookPoint.INPUT_BEFORE,
        "context": HookPoint.CONTEXT_AFTER,
        "tool_result": HookPoint.TOOL_AFTER,
        "output": HookPoint.OUTPUT_BEFORE,
        "stream": HookPoint.STREAM_CHUNK,
    }[stage]
    with _session_run() as harness:
        async with harness.session() as session:
            guard = Guard(id="slow", provider=_Slow(build(subject.contribution)))
            bus = HookBus(
                [
                    Registration(
                        name="slow",
                        handler=guard_handler(stage, [guard], "slow"),  # pyright: ignore[reportArgumentType]
                        hooks=frozenset({hook}),
                        band=Band.BASELINE,
                        fail_mode="closed",
                        timeout=timedelta(milliseconds=20),
                    )
                ]
            )
            result = await bus.emit(
                hook, sample_event(hook, "hello"), session.envelope, session.trace
            )
            outcome = result.outcome
            if not isinstance(outcome, Block):
                raise AssertionError(f"expected Block, got {outcome.kind}")
            _expect(outcome.code == "middleware_timeout", f"expected a timeout, got {outcome.code}")
            provider = build(subject.contribution)
            with anyio.CancelScope() as scope:
                scope.cancel()
                await provider.check("hello", session.envelope)


@contextmanager
def _captured_logs() -> Iterator[list[str]]:
    lines: list[str] = []

    class Collect(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            lines.append(self.format(record))

    handler = Collect(level=logging.DEBUG)
    root = logging.getLogger()
    previous = root.level
    root.addHandler(handler)
    root.setLevel(logging.DEBUG)
    try:
        yield lines
    finally:
        root.removeHandler(handler)
        root.setLevel(previous)


def _otel() -> tuple[Telemetry, Callable[[], list[str]]] | None:
    try:
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import SimpleSpanProcessor
        from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
            InMemorySpanExporter,
        )
    except ImportError:
        return None
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))

    def spans() -> list[str]:
        return [
            f"{span.name} {dict(span.attributes or {})} "
            f"{[(e.name, dict(e.attributes or {})) for e in span.events]}"
            for span in exporter.get_finished_spans()
        ]

    return Telemetry(tracer_provider=provider), spans


async def check_no_raw_content(subject: Subject) -> None:
    """Content passing through a guard or model provider never reaches logs, spans or
    traces (R9). Needs ``opentelemetry-sdk`` for the span part."""
    item = subject.item
    if not isinstance(item, ProviderInfo) or item.port not in ("Guardrail", "ModelProvider"):
        return
    otel = _otel()
    telemetry, spans = otel if otel is not None else (None, lambda: list[str]())
    with _captured_logs() as logs:
        if item.port == "Guardrail":
            guard = {"id": "g", "use": subject.name, **_settings(item.sample)}
            harness = harness_for_test(
                subject.spec(guardrails={"input": [guard]}),
                model=scripted(output({"pass": True})),
                telemetry=telemetry,
            )
            session = harness.session()
            try:
                async with session as s:
                    await s.guard("input", f"Please mail {CANARY} the details")
            except RunInterrupted:
                pass
            result = session.result
        else:
            provider = build(subject.contribution)
            harness = harness_for_test({}, model=provider, telemetry=telemetry)
            session = harness.session()
            try:
                async with session as s:
                    await s.generate(prompt=None, messages=list(sample_request(CANARY).messages))
            except (RunInterrupted, ProviderError):
                pass
            result = session.result
    _expect(result is not None)
    assert_no_content([result, logs, spans()], CANARY)


async def check_latency(subject: Subject, runs: int = 20) -> None:
    """The p95 of ``runs`` calls stays within the declared latency class."""
    item = subject.item
    if not isinstance(item, ProviderInfo) or item.port not in (
        "Guardrail",
        "Decider",
        "ModelProvider",
        "StateStore",
    ):
        return
    limit = LATENCY_LIMITS[item.latency_class]
    provider = build(subject.contribution)
    durations: list[float] = []
    with _session_run() as harness:
        async with harness.session() as session:
            for index in range(runs):
                started = time.perf_counter()
                if item.port == "Guardrail":
                    await provider.check(SAMPLE_TEXTS[index % len(SAMPLE_TEXTS)], session.envelope)
                elif item.port == "Decider":
                    await provider(sample_decision_request())
                elif item.port == "ModelProvider":
                    try:
                        await provider.generate(sample_request(), session.envelope)
                    except ProviderError:
                        return  # a live provider that refuses the network in test mode
                else:
                    await provider.get_run("run_missing")
                durations.append(time.perf_counter() - started)
    if item.port == "StateStore":
        await provider.aclose()
    p95 = sorted(durations)[max(0, int(len(durations) * 0.95) - 1)]
    _expect(
        p95 <= limit,
        f"{item.name}: p95 {p95 * 1000:.1f}ms is over {item.latency_class} ({limit * 1000:.0f}ms)",
    )


# --- middleware, runners, adapters ---------------------------------------------------------------


async def check_middleware(subject: Subject) -> None:
    """Answers each declared hook with an outcome (or ``None``), never by raising."""
    item = subject.item
    if not isinstance(item, MiddlewareDef):
        return
    _expect(item.band is not Band.BASELINE, "a middleware can't declare the baseline band (S8)")
    handler = build(subject.contribution)
    for hook in item.hooks:
        event = sample_event(hook, "hello")
        answer = await handler(event, _env())
        _expect(
            answer is None or isinstance(answer, Continue | Retry | Escalate | Suspend | Block),
            f"{subject.name} answered {hook.value} with {type(answer).__name__}",
        )
        if isinstance(answer, Continue) and answer.modified is not None:
            _expect(
                type(answer.modified) is type(event), f"{subject.name} changed the payload type"
            )


async def check_runner(subject: Subject) -> None:
    """A task runs to a final state and fires only hooks the runner declares (R4)."""
    item = subject.item
    if not isinstance(item, RunnerInfo):
        return
    runner = {"use": subject.name, **_settings(item.sample)}
    harness = harness_for_test(
        subject.spec(tasks={"conformance": {"runner": runner}}), model=scripted("ok")
    )
    result = await harness.run("conformance", "hello")
    _expect(
        result.status.is_terminal or result.status is RunStatus.AWAITING_APPROVAL, result.status
    )
    fired = {HookPoint(h) for h in hooks_fired(result)}
    undeclared = fired - item.reaches
    _expect(
        not undeclared,
        f"runner {subject.name} fired undeclared hooks {sorted(h.value for h in undeclared)}",
    )


async def check_adapter(subject: Subject) -> None:
    """One call through the adapter fires its declared hooks, in lifecycle order (R4)."""
    item = subject.item
    if not isinstance(item, AdapterInfo):
        return
    if item.sample is None:
        raise AssertionError(f"adapter {subject.name} needs sample= for conformance (T5)")
    sample = item.sample()
    _expect(isinstance(sample, AdapterSample), "an adapter sample returns an AdapterSample")
    harness = harness_for_test(subject.spec())
    wrapped = harness.instrument(sample.target, adapter=subject.name)
    seen: list[HookPoint] = []

    async def record(event: Any, env: Envelope) -> None:
        seen.append(HookPoint(event.hook))

    harness._bus.add(
        Registration(
            name="conformance.audit",
            handler=record,
            hooks=frozenset(HookPoint),
            band=Band.APP,
            fail_mode="closed",
        )
    )
    await sample.call(wrapped)
    fired = set(seen)
    _expect(
        fired <= item.reaches,
        f"fired undeclared hooks {sorted(h.value for h in fired - item.reaches)}",
    )
    missing = (item.reaches - _CONDITIONAL) - fired
    _expect(not missing, f"declared but didn't fire {sorted(h.value for h in missing)}")
    first: list[HookPoint] = []
    for hook in seen:
        if hook not in first:
            first.append(hook)
    _expect(
        first == sorted(first, key=LIFECYCLE.index),
        f"hooks fired out of order: {[h.value for h in first]}",
    )


CHECKS: Final = (
    ("builds", check_builds),
    ("results", check_results),
    ("deterministic", check_deterministic),
    ("timeout", check_timeout_blocks),
    ("no_raw_content", check_no_raw_content),
    ("latency", check_latency),
    ("middleware", check_middleware),
    ("runner", check_runner),
    ("adapter", check_adapter),
)
"""Each contribution check, by name."""


def applies(check: str, subject: Subject) -> bool:
    """Whether ``check`` has anything to verify for ``subject``."""
    item = subject.item
    if check == "builds":
        return True
    if isinstance(item, ProviderInfo):
        if check == "results":
            return True
        if check == "deterministic":
            return item.deterministic and item.port in ("Guardrail", "Decider", "ModelProvider")
        if check == "timeout":
            return item.port == "Guardrail"
        if check == "no_raw_content":
            return item.port in ("Guardrail", "ModelProvider")
        if check == "latency":
            return item.port in ("Guardrail", "Decider", "ModelProvider", "StateStore")
        return False
    return (
        (check == "middleware" and isinstance(item, MiddlewareDef))
        or (check == "runner" and isinstance(item, RunnerInfo))
        or (check == "adapter" and isinstance(item, AdapterInfo))
    )


def subjects(loaded: LoadedPlugin) -> list[Subject]:
    """Every contribution of ``loaded``, ready to check."""
    return [Subject(loaded, contribution) for contribution in loaded.plugin.contributions()]
