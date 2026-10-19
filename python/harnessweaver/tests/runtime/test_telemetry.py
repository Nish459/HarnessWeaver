"""Telemetry through the OpenTelemetry API: spans, metrics and content capture (R9)."""

import pytest
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import InMemoryMetricReader
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.semconv._incubating.attributes import gen_ai_attributes as semconv
from opentelemetry.semconv._incubating.metrics import gen_ai_metrics

import harnessweaver as hw
from harnessweaver.core.telemetry import GenAI, Telemetry
from harnessweaver.core.trace import TraceKind
from harnessweaver.errors import RunBlocked

from .conftest import Builder, spec
from .l1_support import scripted

pytestmark = pytest.mark.anyio


def otel() -> tuple[Telemetry, InMemorySpanExporter, InMemoryMetricReader]:
    exporter = InMemorySpanExporter()
    tracer_provider = TracerProvider()
    tracer_provider.add_span_processor(SimpleSpanProcessor(exporter))
    reader = InMemoryMetricReader()
    return (
        Telemetry(
            tracer_provider=tracer_provider, meter_provider=MeterProvider(metric_readers=[reader])
        ),
        exporter,
        reader,
    )


def test_pinned_names_match_the_installed_conventions() -> None:
    assert GenAI.OPERATION_NAME == semconv.GEN_AI_OPERATION_NAME
    assert GenAI.PROVIDER_NAME == semconv.GEN_AI_PROVIDER_NAME
    assert GenAI.REQUEST_MODEL == semconv.GEN_AI_REQUEST_MODEL
    assert GenAI.REQUEST_MAX_TOKENS == semconv.GEN_AI_REQUEST_MAX_TOKENS
    assert GenAI.REQUEST_TEMPERATURE == semconv.GEN_AI_REQUEST_TEMPERATURE
    assert GenAI.REQUEST_STREAM == semconv.GEN_AI_REQUEST_STREAM
    assert GenAI.RESPONSE_MODEL == semconv.GEN_AI_RESPONSE_MODEL
    assert GenAI.RESPONSE_FINISH_REASONS == semconv.GEN_AI_RESPONSE_FINISH_REASONS
    assert GenAI.USAGE_INPUT_TOKENS == semconv.GEN_AI_USAGE_INPUT_TOKENS
    assert GenAI.USAGE_OUTPUT_TOKENS == semconv.GEN_AI_USAGE_OUTPUT_TOKENS
    assert GenAI.TOKEN_TYPE == semconv.GEN_AI_TOKEN_TYPE
    assert GenAI.TOOL_NAME == semconv.GEN_AI_TOOL_NAME
    assert GenAI.TOOL_CALL_ID == semconv.GEN_AI_TOOL_CALL_ID
    assert GenAI.TOOL_TYPE == semconv.GEN_AI_TOOL_TYPE
    assert GenAI.TOOL_CALL_ARGUMENTS == semconv.GEN_AI_TOOL_CALL_ARGUMENTS
    assert GenAI.TOOL_CALL_RESULT == semconv.GEN_AI_TOOL_CALL_RESULT
    assert GenAI.INPUT_MESSAGES == semconv.GEN_AI_INPUT_MESSAGES
    assert GenAI.OUTPUT_MESSAGES == semconv.GEN_AI_OUTPUT_MESSAGES
    assert GenAI.CLIENT_TOKEN_USAGE == gen_ai_metrics.GEN_AI_CLIENT_TOKEN_USAGE
    assert GenAI.CLIENT_OPERATION_DURATION == gen_ai_metrics.GEN_AI_CLIENT_OPERATION_DURATION


@pytest.mark.parametrize("capture", [False, True])
async def test_spans_metrics_and_content_capture(build: Builder, capture: bool) -> None:
    telemetry, exporter, reader = otel()
    call = {"id": "c1", "name": "lookup", "arguments": {"email": "bob@example.com"}}
    harness = build(
        spec(
            models=scripted(
                {
                    "tool_calls": [call],
                    "model": "m-1",
                    "usage": {"input_tokens": 7, "output_tokens": 3},
                },
                after_tool_unused=True,
                rules=[
                    {
                        "role": "tool",
                        "reply": {
                            "text": "done for bob@example.com",
                            "model": "m-1",
                            "cost_usd": 0.5,
                        },
                    }
                ],
            ),
            observability={"capture_content": capture},
            guardrails={
                "input": [{"id": "pii", "use": "pii.regex"}],
                "output": [{"id": "pii-out", "use": "pii.regex"}],
            },
            middleware=[{"use": "testkit.flaky"}],
            tasks={"t": {"runner": "direct", "tools": ["lookup"]}},
        ),
        telemetry=telemetry,
    )
    result = await harness.run("t", "ask about bob@example.com", tenant="acme")
    assert result.ok
    spans = {span.name: span for span in exporter.get_finished_spans()}
    run = spans["harness.run"]
    assert run.attributes is not None
    assert run.attributes["harness.run.status"] == "completed"
    assert run.attributes["harness.tenant"] == "acme"
    assert result.trace
    assert run.context is not None
    chat = spans["chat unknown"]
    assert chat.attributes is not None
    assert chat.attributes[GenAI.OPERATION_NAME] == "chat"
    assert chat.attributes[GenAI.PROVIDER_NAME] == "scripted"
    tool = spans["execute_tool lookup"]
    assert tool.attributes is not None
    assert tool.attributes[GenAI.TOOL_NAME] == "lookup"
    assert any(s.name == "harness.guard" for s in exporter.get_finished_spans())
    assert chat.parent is not None
    assert chat.parent.span_id == run.context.span_id
    events = [e for s in exporter.get_finished_spans() for e in s.events]
    assert any(e.name == "harness.outcome" for e in events)
    everything = "".join(str(s.attributes) for s in exporter.get_finished_spans())
    if not capture:
        assert "bob@example.com" not in everything  # R9: no content unless asked for
    if capture:
        assert "[EMAIL]" in str(chat.attributes[GenAI.INPUT_MESSAGES])
        assert GenAI.TOOL_CALL_ARGUMENTS in tool.attributes
    else:
        assert GenAI.INPUT_MESSAGES not in chat.attributes
    metrics = reader.get_metrics_data()
    assert metrics is not None
    names = {
        m.name for rm in metrics.resource_metrics for sm in rm.scope_metrics for m in sm.metrics
    }
    assert {GenAI.CLIENT_TOKEN_USAGE, GenAI.CLIENT_OPERATION_DURATION, "harness.cost"} <= names


async def test_sessions_and_approvals_have_spans(build: Builder) -> None:
    telemetry, exporter, _ = otel()
    harness = build(
        spec(
            models=scripted({"text": "x"}),
            middleware=[
                {
                    "use": "testkit.script",
                    "rules": [{"hook": "output.before", "outcome": "suspend"}],
                }
            ],
            tasks={"t": {"runner": "direct"}},
        ),
        telemetry=telemetry,
    )
    async with harness.session() as s:
        await s.decide("intent", default="a")
    with pytest.raises(RunBlocked):
        async with harness.session() as s:
            await s.tool("missing")
    first = await harness.run("t", "q")
    assert first.approval is not None
    await harness.approve(first.run_id, first.approval.approval_id, approver="x")
    names = [span.name for span in exporter.get_finished_spans()]
    assert names.count("harness.run") == 4
    assert names.count("harness.approval") == 2
    assert "harness.decision" in names
    statuses = [
        span.attributes.get("harness.run.status")
        for span in exporter.get_finished_spans()
        if span.name == "harness.run" and span.attributes
    ]
    assert statuses == ["completed", "blocked", "awaiting_approval", "completed"]


def test_traces_without_an_sdk_are_free() -> None:
    telemetry = Telemetry()
    envelope = hw.Envelope.new(tenant="t", principal="p")
    with telemetry.run_scope(envelope) as span:
        assert Telemetry.trace_id(span) is None
    assert TraceKind.HOOK.value == "hook"
