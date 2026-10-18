"""L1 modules in a running harness: guardrails, validation rules, the scripted model, telemetry."""

import json
from pathlib import Path
from typing import Any

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
from harnessweaver.errors import ProviderError, RunBlocked, SpecError
from harnessweaver.modules.models import ScriptedModel

from .conftest import Builder, spec

pytestmark = pytest.mark.anyio

SUMMARY = "hw_testkit:Summary"


def scripted(*replies: Any, **settings: Any) -> dict[str, Any]:
    return {"provider": "scripted", "replies": list(replies), **settings}


def org_profile(tmp_path: Path, **body: Any) -> str:
    directory = tmp_path / ".harness" / "profiles"
    directory.mkdir(parents=True, exist_ok=True)
    document = {
        "apiVersion": "harnessweaver/v1",
        "kind": "Profile",
        "metadata": {"name": "acme-baseline", "version": "1.0.0"},
        **body,
    }
    (directory / "acme-baseline.yaml").write_text(json.dumps(document), encoding="ascii")
    return "org://acme-baseline"


# --- guardrails ----------------------------------------------------------------------------------


async def test_an_extraction_task_repairs_once_then_escalates(build: Builder, testkit: Any) -> None:
    harness = build(
        spec(
            extends=["profile://extraction"],
            models=scripted({"output": {"title": "Q3"}}),
            tasks={"summarize": {"runner": "direct", "output": SUMMARY}},
        )
    )
    result = await harness.run("summarize", "summary for alice@example.com")
    assert result.status is hw.RunStatus.ESCALATED
    assert result.error is not None
    assert result.error.details["code"] == "validation_failed"
    model = harness.registry.provider("ModelProvider", "scripted")
    assert model.name == "scripted"
    chain = harness.hooks("summarize")
    assert [(r.name, r.band) for r in chain[hw.HookPoint.INPUT_BEFORE]] == [
        ("guardrails.input[extraction-pii]", hw.Band.PLATFORM)
    ]


async def test_guards_redact_input_and_block_secret_output(build: Builder, testkit: Any) -> None:
    harness = build(
        spec(
            extends=["profile://extraction"],
            models=scripted({"output": {"title": "key AKIAIOSFODNN7EXAMPLE", "words": 2}}),
            tasks={"summarize": {"runner": "direct", "output": SUMMARY}},
        )
    )
    result = await harness.run("summarize", "summary for alice@example.com")
    assert result.status is hw.RunStatus.BLOCKED
    assert result.error is not None
    assert result.error.details["code"] == "guard_blocked"
    scripted_model = _model(harness)
    assert scripted_model.requests[0].messages[-1].content == "summary for [EMAIL]"
    assert "AKIA" not in result.model_dump_json()  # R9: reasons and findings only


def _model(harness: hw.Harness) -> ScriptedModel:
    provider = harness._models.provider
    assert isinstance(provider, ScriptedModel)
    return provider


async def test_guard_bands_follow_the_layer_that_declared_them(
    build: Builder, tmp_path: Path
) -> None:
    ref = org_profile(
        tmp_path, guardrails={"output": [{"id": "org-secrets", "use": "secrets.scan"}]}
    )
    harness = build(
        spec(
            extends=[ref, "profile://extraction"],
            models=scripted({"text": "x"}),
            guardrails={
                "output": [{"id": "app-topics", "use": "topic.deny", "topics": {"t": ["x"]}}]
            },
            tasks={
                "t": {
                    "runner": "direct",
                    "guardrails": {
                        "output": [{"id": "task-size", "use": "size.limit", "max_chars": 9}]
                    },
                }
            },
        )
    )
    chain = harness.hooks("t")[hw.HookPoint.OUTPUT_BEFORE]
    assert [(r.name, r.band) for r in chain] == [
        ("guardrails.output[org-secrets]", hw.Band.BASELINE),
        ("guardrails.output[extraction-secrets]", hw.Band.PLATFORM),
        ("guardrails.output[app-topics]", hw.Band.APP),
        ("tasks.t.guardrails.output[task-size]", hw.Band.TASK),
    ]
    assert [r.name for r in harness.hooks("other")[hw.HookPoint.OUTPUT_BEFORE]][-1] != (
        "tasks.t.guardrails.output[task-size]"
    )


async def test_a_shadow_guard_is_traced_but_does_not_act(build: Builder) -> None:
    harness = build(
        spec(
            models=scripted({"text": "your key is AKIAIOSFODNN7EXAMPLE"}),
            guardrails={"output": [{"id": "keys", "use": "secrets.scan", "mode": "log_only"}]},
            tasks={"t": {"runner": "direct"}},
        )
    )
    result = await harness.run("t", "q")
    assert result.ok
    shadow = [
        e
        for e in result.trace
        if e.kind is TraceKind.OUTCOME and (e.reason or "").startswith("would block")
    ]
    assert len(shadow) == 1
    assert shadow[0].source == "guardrails.output[keys]"


async def test_guard_configuration_errors(build: Builder) -> None:
    with pytest.raises(SpecError, match="stage"):
        build(
            spec(
                models=scripted({"text": "x"}),
                guardrails={"tool_result": [{"use": "llm.judge", "criteria": "c"}]},
            )
        )
    with pytest.raises(SpecError, match="sidecar"):
        build(
            spec(
                models=scripted({"text": "x"}),
                guardrails={"input": [{"use": "pii.regex", "where": "sidecar"}]},
            )
        )
    with pytest.raises(SpecError, match="max_chars or max_bytes"):
        build(spec(models=scripted({"text": "x"}), guardrails={"input": [{"use": "size.limit"}]}))
    with pytest.raises(SpecError, match="invalid pattern"):
        build(
            spec(
                models=scripted({"text": "x"}),
                guardrails={"input": [{"use": "regex.deny", "patterns": ["("]}]},
            )
        )
    with pytest.raises(SpecError, match="unknown secret kinds"):
        build(
            spec(
                models=scripted({"text": "x"}),
                guardrails={"input": [{"use": "secrets.scan", "kinds": ["x"]}]},
            )
        )


async def test_a_baseline_guard_must_fail_closed(build: Builder, tmp_path: Path) -> None:
    ref = org_profile(
        tmp_path, guardrails={"input": [{"id": "pii", "use": "pii.regex", "fail_mode": "open"}]}
    )
    with pytest.raises(SpecError, match="R2"):
        build(spec(models=scripted({"text": "x"}), extends=[ref]))


async def test_parallel_guards_and_member_failures(build: Builder) -> None:
    harness = build(
        spec(
            models=scripted({"text": "x"}),
            guardrails={
                "input": [
                    {"id": "inj", "use": "injection.heuristic", "parallel": True},
                    {
                        "id": "judge",
                        "use": "llm.judge",
                        "criteria": "be nice",
                        "parallel": True,
                        "fail_mode": "open",
                        "timeout": "1s",
                    },
                    {"id": "pii", "use": "pii.regex", "parallel": True, "mode": "log_only"},
                ]
            },
            tasks={"t": {"runner": "direct"}},
        )
    )
    (group,) = harness.hooks("t")[hw.HookPoint.INPUT_BEFORE]
    assert group.name == "guardrails.input[inj+judge+pii]"
    result = await harness.run("t", "hello bob@example.com")
    # The judge got the scripted "x", which isn't JSON: it fails open; pii is shadow only.
    assert result.ok
    reasons = [e.reason or "" for e in result.trace]
    assert any("guard failed (ProviderError)" in r for r in reasons)
    assert any("would redact: pii" in r for r in reasons)


async def test_the_llm_judge(build: Builder) -> None:
    harness = build(
        spec(
            models={
                "provider": "scripted",
                "rules": [
                    {
                        "contains": "rude",
                        "reply": {"output": {"pass": False, "reason": "rude words"}},
                    },
                    {"role": "user", "contains": "polite", "reply": {"output": {"pass": True}}},
                ],
                "replies": [{"text": "a polite answer"}],
            },
            guardrails={"output": [{"id": "judge", "use": "llm.judge", "criteria": "no rudeness"}]},
            tasks={"t": {"runner": "direct"}},
        )
    )
    assert (await harness.run("t", "q")).ok
    rude = build(
        spec(
            models={
                "provider": "scripted",
                "rules": [
                    {
                        "role": "user",
                        "contains": "rude",
                        "reply": {"output": {"pass": False, "reason": "quote"}},
                    }
                ],
                "replies": [{"text": "a rude answer"}],
            },
            guardrails={"output": [{"id": "judge", "use": "llm.judge", "criteria": "no rudeness"}]},
            tasks={"t": {"runner": "direct"}},
        )
    )
    result = await rude.run("t", "q")
    assert result.status is hw.RunStatus.BLOCKED
    assert "quote" not in result.model_dump_json()  # the judge's words aren't kept (R9)


async def test_the_judge_needs_a_run_and_json() -> None:
    from harnessweaver.modules.guardrails import LlmJudge
    from harnessweaver.modules.guardrails.providers import JudgeConfig

    judge = LlmJudge(JudgeConfig(criteria="c"))
    with pytest.raises(ProviderError, match="active run"):
        await judge.check("x", hw.Envelope.new(tenant="t", principal="p"))


# --- validation rules ----------------------------------------------------------------------------


async def test_validation_rules_ask_for_repairs(build: Builder, tmp_path: Path) -> None:
    ref = org_profile(
        tmp_path,
        validation={
            "rules": [
                {"id": "positive", "when": "output.words <= 0", "message": "words must be positive"}
            ]
        },
    )
    harness = build(
        spec(
            extends=[ref],
            models=scripted(
                {"output": {"title": "T", "words": 0}}, {"output": {"title": "T", "words": 3}}
            ),
            validation={
                "rules": [
                    {"id": "title", "when": "size(output.title) == 0", "message": "needs a title"}
                ]
            },
            tasks={"t": {"runner": "direct", "output": SUMMARY}},
        )
    )
    (org, app) = harness.hooks("t")[hw.HookPoint.OUTPUT_BEFORE]
    assert (org.name, org.band) == ("validation.rules[positive]", hw.Band.BASELINE)
    assert (app.name, app.band) == ("validation.rules[title]", hw.Band.APP)
    result = await harness.run("t", "q")
    assert result.output == {"title": "T", "words": 3}
    assert "words must be positive" in _model(harness).requests[1].messages[-1].content


async def test_a_rule_that_cannot_be_evaluated_counts_as_broken(build: Builder) -> None:
    harness = build(
        spec(
            models=scripted({"text": "plain"}),
            validation={
                "max_repairs": 0,
                "rules": [{"when": "output.total < 0", "message": "bad total"}],
            },
            tasks={"t": {"runner": "direct"}},
        )
    )
    result = await harness.run("t", "q")
    assert result.status is hw.RunStatus.BLOCKED
    assert result.error is not None
    assert "couldn't be checked" in result.error.message


# --- the scripted model --------------------------------------------------------------------------


async def test_the_scripted_model_follows_rules_then_replies(testkit: Any) -> None:
    model = ScriptedModel.of(
        "first",
        {"output": {"a": 1}},
        rules=[{"contains": "REFUND", "times": 1, "reply": {"tool_calls": [{"name": "refund"}]}}],
        repeat_last=False,
    )
    env = hw.Envelope.new(tenant="t", principal="p")

    def ask(text: str) -> hw.ModelRequest:
        return hw.ModelRequest(messages=(hw.Message.user(text),))

    refund = await model.generate(ask("please refund"), env)
    assert refund.tool_calls[0].id == "call_1"
    assert refund.finish_reason == "tool_calls"
    assert (await model.generate(ask("please refund"), env)).text == "first"
    structured = await model.generate(ask("x"), env)
    assert structured.output == {"a": 1}
    assert structured.text == '{"a": 1}'
    assert structured.usage.input_tokens == 1
    with pytest.raises(ProviderError, match="no reply left"):
        await model.generate(ask("x"), env)
    assert len(model.requests) == 4
    chunks = [
        c
        async for c in ScriptedModel.of({"text": "ab", "chunks": ["a", "b"]}).stream(ask("x"), env)
    ]
    assert [getattr(c, "delta", None) for c in chunks] == ["a", "b", None]
    with pytest.raises(ProviderError, match="fails"):
        await ScriptedModel.of({"fail": True}).generate(ask("x"), env)
    with pytest.raises(ValueError, match="replies or rules"):
        ScriptedModel.of()
    with pytest.raises(ValueError, match="invalid pattern"):
        ScriptedModel.of("x", rules=[{"matches": "(", "reply": {}}])
    matching = ScriptedModel.of(
        "x", rules=[{"matches": "^go$", "role": "user", "reply": {"text": "went"}}]
    )
    assert (await matching.generate(ask("go"), env)).text == "went"
    assert (await matching.generate(hw.ModelRequest(messages=()), env)).text == "x"


async def test_scripted_ignores_settings_meant_for_a_real_provider(build: Builder) -> None:
    harness = build(
        spec(
            models=scripted({"text": "offline"}, base_url="http://litellm:4000"),
            tasks={"t": {"runner": "direct"}},
        )
    )
    assert (await harness.run("t", "q")).output == "offline"


# --- telemetry -----------------------------------------------------------------------------------


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
