"""No raw content in logs, spans or traces (R9), and latency within the declared class."""

import logging
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager

from loguru import logger

from harnessweaver.core.errors import ProviderError, RunInterrupted, ValidationFailed
from harnessweaver.core.plugins import (
    ProviderInfo,
)
from harnessweaver.core.telemetry import Telemetry
from harnessweaver.testing.conformance.builds import build, sample_settings
from harnessweaver.testing.conformance.common import LATENCY_LIMITS, Subject, expect
from harnessweaver.testing.conformance.results import session_run
from harnessweaver.testing.kit import harness_for_test, output, scripted
from harnessweaver.testing.samples import (
    CANARY,
    SAMPLE_TEXTS,
    sample_decision_request,
    sample_policy_requests,
    sample_request,
)
from harnessweaver.testing.traces import assert_no_content

__all__ = ["check_latency", "check_no_raw_content"]


@contextmanager
def _captured_logs(module: str) -> Iterator[list[str]]:
    """Everything logged meanwhile, through loguru and the standard library.

    The harness's and the plugin's loguru logs are off by default (ADR-0024), so
    they are turned on for the check and back off afterwards.
    """
    lines: list[str] = []

    class Collect(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            lines.append(self.format(record))

    handler = Collect(level=logging.DEBUG)
    root = logging.getLogger()
    previous = root.level
    root.addHandler(handler)
    root.setLevel(logging.DEBUG)
    names = sorted({"harnessweaver", module.split(".")[0]})
    for name in names:
        logger.enable(name)
    sink = logger.add(
        lines.append, level="TRACE", format="{level} {name} {message} {extra} {exception}"
    )
    try:
        yield lines
    finally:
        logger.remove(sink)
        for name in names:
            logger.disable(name)
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
    with _captured_logs(subject.plugin.source.module) as logs:
        if item.port == "Guardrail":
            guard = {"id": "g", "use": subject.name, **sample_settings(item.sample)}
            stage = "input" if not item.stages or "input" in item.stages else "output"
            harness = harness_for_test(
                subject.spec(guardrails={stage: [guard]}),
                model=scripted(output({"pass": True})),
                telemetry=telemetry,
            )
            session = harness.session()
            content = f"Please mail {CANARY} the details about refunds today."
            try:
                async with session as s:
                    if stage == "input":
                        await s.guard("input", content)
                    else:
                        await s.validate("output", content)
            except (RunInterrupted, ValidationFailed):
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
    expect(result is not None)
    assert_no_content([result, logs, spans()], CANARY)


async def check_latency(subject: Subject, runs: int = 20) -> None:
    """The p95 of ``runs`` calls stays within the declared latency class."""
    item = subject.item
    if not isinstance(item, ProviderInfo) or item.port not in (
        "Guardrail",
        "Decider",
        "ModelProvider",
        "StateStore",
        "PolicyEngine",
    ):
        return
    limit = LATENCY_LIMITS[item.latency_class]
    requests = sample_policy_requests()
    provider = build(subject.contribution)
    durations: list[float] = []
    with session_run() as harness:
        async with harness.session() as session:
            for index in range(runs):
                started = time.perf_counter()
                if item.port == "Guardrail":
                    await provider.check(SAMPLE_TEXTS[index % len(SAMPLE_TEXTS)], session.envelope)
                elif item.port == "Decider":
                    await provider(sample_decision_request())
                elif item.port == "PolicyEngine":
                    await provider.decide(requests[index % len(requests)])
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
    expect(
        p95 <= limit,
        f"{item.name}: p95 {p95 * 1000:.1f}ms is over {item.latency_class} ({limit * 1000:.0f}ms)",
    )
