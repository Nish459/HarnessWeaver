"""Standalone sessions: the app owns the flow, the harness governs each call."""

from typing import Any

import pytest

import harnessweaver as hw
from harnessweaver.core.trace import TraceKind
from harnessweaver.errors import RunBlocked, RunEscalated, SpecError, ValidationFailed

from .conftest import Builder, scripted, spec

pytestmark = pytest.mark.anyio


def script(*rules: dict[str, Any]) -> dict[str, Any]:
    return {"use": "testkit.script", "rules": list(rules)}


async def test_generate_with_a_prompt_and_typed_output(build: Builder, testkit: Any) -> None:
    harness = build(spec(models=scripted({"output": {"title": "T", "words": 1}})))
    async with harness.session(task="support", principal="alice") as s:
        summary = await s.generate(
            prompt="reply@1", output=testkit.Summary, route="billing", customer="alice"
        )
        assert isinstance(summary, testkit.Summary)
        assert s.envelope.principal.id == "alice"
        assert s.run_id.startswith("run_")
        assert len(s.trace) > 0
        assert s.run_context.task_name == "support"
    assert s.result is not None
    assert s.result.ok
    assert s.result.output == {"title": "T", "words": 1}
    assert testkit.RECORDER.requests[0].messages[0].content == "Route billing. Customer: alice"


async def test_generate_repairs_and_gives_up(build: Builder, testkit: Any) -> None:
    harness = build(spec(models=scripted({"text": "{}"}, {"text": "still {}"})))
    session = harness.session()
    with pytest.raises(RunBlocked):
        async with session as s:
            await s.generate(messages=[hw.Message.user("go")], output=testkit.Summary)
    assert session.result is not None
    assert session.result.status is hw.RunStatus.BLOCKED
    assert len(testkit.RECORDER.requests) == 2
    assert [e.reason for e in session.result.trace if e.code == "repair"] == [
        "repair 1: title: Field required; words: Field required"
    ]


async def test_streaming_fires_stream_chunk(build: Builder) -> None:
    harness = build(
        spec(
            models=scripted({"chunks": ["one ", "two"]}),
            middleware=[
                script({"hook": "stream.chunk", "outcome": "modify", "value": "TWO", "times": 0}),
                {"use": "testkit.audit"},
            ],
        )
    )
    async with harness.session() as s:
        text = await s.generate(prompt="reply@1", stream=True, route="r", customer="c")
    assert text == "one two"
    assert s.result is not None
    chunks = [
        e
        for e in s.result.trace
        if e.kind is TraceKind.HOOK and e.hook is hw.HookPoint.STREAM_CHUNK
    ]
    assert len(chunks) == 2


async def test_a_chunk_can_be_rewritten_or_cut(build: Builder) -> None:
    harness = build(
        spec(
            models=scripted({"chunks": ["fine ", "bad"]}),
            middleware=[script({"hook": "stream.chunk", "outcome": "modify", "value": "***"})],
        )
    )
    async with harness.session() as s:
        assert await s.generate(prompt="reply@1", stream=True, route="r", customer="c") == "******"

    cutting = build(
        spec(
            models=scripted({"chunks": ["fine ", "bad"]}),
            middleware=[script({"hook": "stream.chunk", "outcome": "block", "reason": "unsafe"})],
        )
    )
    with pytest.raises(RunBlocked, match="unsafe"):
        async with cutting.session() as s:
            await s.generate(prompt="reply@1", stream=True, route="r", customer="c")


async def test_tools_routing_context_and_labels(build: Builder) -> None:
    harness = build(
        spec(
            models=scripted({"text": "x"}),
            middleware=[
                script(
                    {"hook": "route.decide", "outcome": "modify", "value": "billing"},
                    {"hook": "context.after", "outcome": "modify", "value": "d2"},
                )
            ],
        )
    )
    items = [
        hw.ContextItem(id="d1", content="a", source="kb", untrusted=False),
        hw.ContextItem(id="d2", content="b", source="kb", untrusted=True),
    ]
    async with harness.session() as s:
        decision = await s.decide("intent", text="refund", options=["billing", "other"])
        kept = await s.context("kb").check(items, query="refund")
        customer = await s.tool("lookup", id="1")
    assert decision.choice == "billing"
    assert decision.kind is hw.DecisionKind.EXACT
    assert [i.id for i in kept] == ["d1"]
    assert customer == {"customer": "alice", "tier": "gold"}
    assert s.envelope.labels.private_seen
    assert s.envelope.labels.untrusted_seen
    assert s.envelope.labels.sources == ("tool:lookup",)
    assert s.result is not None
    note = next(e for e in s.result.trace if e.source == "harness.decision")
    assert note.details["choice"] == "billing"


async def test_decide_without_a_router(build: Builder) -> None:
    harness = build(spec(models=scripted({"text": "x"})))
    async with harness.session() as s:
        assert (await s.decide("intent", default="other")).choice == "other"
        assert (await s.decide("intent")).kind is hw.DecisionKind.ABSTAIN


async def test_guard_and_validate(build: Builder, testkit: Any) -> None:
    harness = build(
        spec(
            models=scripted({"text": "x"}),
            middleware=[
                script(
                    {"hook": "input.before", "outcome": "modify", "value": "[EMAIL]"},
                    {
                        "hook": "output.before",
                        "outcome": "retry",
                        "reason": "cite sources",
                        "times": 1,
                    },
                    {
                        "hook": "output.before",
                        "outcome": "modify",
                        "value": {"title": "Fixed", "words": 1},
                    },
                )
            ],
        )
    )
    async with harness.session() as s:
        assert await s.guard("input", "alice@example.com") == "[EMAIL]"
        with pytest.raises(ValidationFailed, match="cite sources"):
            await s.validate("output", testkit.Summary(title="T", words=2))
        fixed = await s.validate("output", testkit.Summary(title="T", words=2))
        assert fixed == testkit.Summary(title="Fixed", words=1)
        with pytest.raises(SpecError):
            await s.guard("output", "x")  # type: ignore[arg-type]
        with pytest.raises(SpecError):
            await s.validate("input", "x")  # type: ignore[arg-type]
    assert s.result is not None
    assert s.result.output == {"title": "Fixed", "words": 1}


async def test_validate_keeps_an_unchanged_value(build: Builder, testkit: Any) -> None:
    harness = build(spec(models=scripted({"text": "x"})))
    async with harness.session() as s:
        value = testkit.Summary(title="T", words=2)
        assert await s.validate("output", value) is value


async def test_suspend_escalates_in_a_standalone_session(build: Builder, testkit: Any) -> None:
    harness = build(
        spec(
            models=scripted({"text": "x"}),
            middleware=[script({"hook": "tool.before", "outcome": "suspend"})],
        )
    )
    session = harness.session()
    with pytest.raises(RunEscalated):
        async with session as s:
            await s.tool("refund", amount=1)
    assert session.result is not None
    assert session.result.status is hw.RunStatus.ESCALATED
    assert testkit.RECORDER.tool_calls == []


async def test_app_errors_propagate_and_fail_the_run(build: Builder) -> None:
    harness = build(spec(models=scripted({"text": "x"})))
    session = harness.session()
    with pytest.raises(KeyError):
        async with session:
            raise KeyError("app bug")
    result = session.result
    assert result is not None
    assert result.status is hw.RunStatus.FAILED
    assert result.error is not None
    assert result.error.code is hw.errors.ErrorCode.INTERNAL
    hooks = [e.hook for e in result.trace if e.kind is TraceKind.HOOK]
    assert hooks[-2:] == [hw.HookPoint.RUN_ERROR, hw.HookPoint.RUN_END]


async def test_a_blocked_start_raises_on_enter(build: Builder) -> None:
    harness = build(
        spec(
            models=scripted({"text": "x"}),
            middleware=[script({"hook": "run.start", "outcome": "block"})],
        )
    )
    session = harness.session()
    with pytest.raises(RunBlocked):
        async with session:
            pytest.fail("the body must not run")
    assert session.result is not None
    assert session.result.status is hw.RunStatus.BLOCKED


async def test_session_budgets(build: Builder) -> None:
    harness = build(
        spec(
            models=scripted({"text": "x"}),
            budgets={"per_run": {"max_model_calls": 2}},
            tasks={"t": {"runner": "direct", "budget": {"max_model_calls": 1}}},
        )
    )

    async def two_calls() -> None:
        async with harness.session("t") as s:
            await s.generate(messages=[hw.Message.user("1")])
            await s.generate(messages=[hw.Message.user("2")])

    with pytest.raises(RunBlocked):
        await two_calls()
    async with harness.session(budget=hw.Budget(max_tokens=1)) as s:
        assert s.envelope.budget.max_tokens == 1
        assert s.envelope.budget.max_model_calls == 2


async def test_session_misuse(build: Builder) -> None:
    harness = build(spec(models=scripted({"text": "x"})))
    session = harness.session()
    with pytest.raises(SpecError):
        await session.generate(messages=[hw.Message.user("x")])
    async with session as s:
        with pytest.raises(SpecError):
            await s.generate()
        with pytest.raises(SpecError, match=r"wasn't given"):
            await s.prompt("reply@1", route="r")
    with pytest.raises(SpecError):
        async with session:
            pass
    with pytest.raises(SpecError):
        async with hw.Session.for_run(s.run_context):
            pass
