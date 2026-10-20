"""``harness.wrap(agent)``: an app's own Pydantic AI agent, governed (ADR-0037)."""

import asyncio
from collections.abc import Iterator
from typing import Any

import pai_agents
import pytest
from pai_agents import ASKED, RAN, Answer, calls, cancel_order, lookup_order, model, spec, text
from pydantic import JsonValue
from pydantic_ai import Agent, DeferredToolRequests, DeferredToolResults, Tool
from pydantic_ai.messages import ImageUrl, ModelRequest, UserPromptPart

import harnessweaver as hw
from harnessweaver.errors import RunBlocked, RunEscalated, SpecError, UnknownProvider
from harnessweaver.testing import FakeTool, harness_for_test

pytestmark = pytest.mark.anyio

PII = {
    "input": [{"id": "pii-in", "use": "pii.regex"}],
    "output": [{"id": "pii-out", "use": "pii.regex"}],
}
ORDER: dict[str, JsonValue] = {"type": "object", "properties": {"order_id": {"type": "string"}}}
ALWAYS: dict[str, JsonValue] = {"approval": {"when": "true", "approver_role": "ops"}}


def prompt_of(messages: list[Any]) -> str:
    first = messages[0]
    assert isinstance(first, ModelRequest)
    part = next(p for p in first.parts if isinstance(p, UserPromptPart))
    assert isinstance(part.content, str)
    return part.content


def agent(*replies: Any, **options: Any) -> Agent[None, Any]:
    return Agent(model(*replies), tools=[lookup_order], **options)


async def test_a_wrapped_run_is_a_governed_run_of_its_own() -> None:
    harness = harness_for_test(spec(guardrails=PII))
    wrapped = harness.wrap(agent(text("Write to bob@example.com")), tenant="acme")
    result = await wrapped.run("Mail alice@example.com")
    assert result.output == "Write to [EMAIL]"
    assert prompt_of(ASKED[0]) == "Mail [EMAIL]"  # the agent's model got the redacted prompt
    assert pai_agents.hooks() == [
        "run.start",
        "input.before",
        "model.before",
        "model.after",
        "output.before",
        "run.end",
    ]
    (run_id,) = {run for _, run in pai_agents.SEEN}
    record = await harness.result(run_id)
    assert record.status is hw.RunStatus.COMPLETED
    assert record.output == "Write to [EMAIL]"
    assert record.usage.total_tokens > 0


async def test_a_prompt_with_images_has_its_text_checked() -> None:
    image = ImageUrl(url="https://example.com/cat.png")
    harness = harness_for_test(spec(guardrails=PII))
    await harness.wrap(agent(text("ok"))).run(["Mail alice@example.com", image])
    first = ASKED[0][0]
    assert isinstance(first, ModelRequest)
    prompt = next(p for p in first.parts if isinstance(p, UserPromptPart))
    assert prompt.content == ["Mail [EMAIL]", image]


@pytest.fixture
def sync_loop() -> Iterator[None]:
    """``run_sync`` keeps Pydantic AI's event loop open for the next call; close it after."""
    yield
    loop = asyncio.get_event_loop()
    asyncio.set_event_loop(None)
    loop.close()


@pytest.mark.usefixtures("sync_loop")
def test_run_sync_is_governed_too() -> None:
    harness = harness_for_test(spec(guardrails=PII))
    result = harness.wrap(agent(text("fine"))).run_sync("call 555-123-4567")
    assert result.output == "fine"
    assert prompt_of(ASKED[0]) == "call [PHONE]"


async def test_model_middleware_changes_reach_the_agents_model() -> None:
    harness = harness_for_test(spec(middleware=[{"use": "pai_test.hide_codes"}]))
    wrapped = harness.wrap(agent(text("ok"), instructions="Never share the secret."))
    result = await wrapped.run("my secret is 42")
    assert prompt_of(ASKED[0]) == "my [hidden] is 42"
    assert pai_agents.INSTRUCTED == ["Never share the [hidden]."]
    assert prompt_of(result.all_messages()) == "my secret is 42"  # only the request changed


async def test_structured_output_is_checked_and_kept_typed() -> None:
    rules = [{"id": "known", "when": "output.category == 'unknown'", "message": "pick one"}]
    replies = (
        calls(("final_result", {"category": "unknown"})),
        calls(("final_result", {"category": "billing"})),
    )
    harness = harness_for_test(spec(validation={"rules": rules}))
    result = await harness.wrap(agent(*replies, output_type=Answer)).run("hello")
    assert result.output == Answer(category="billing")
    assert len(ASKED) == 2  # the rule asked the agent's model again


async def test_the_agents_tools_are_governed() -> None:
    harness = harness_for_test(spec(), tools=[FakeTool("lookup_order", input_schema=ORDER)])
    replies = (calls(("lookup_order", {"order_id": "7"})), text("shipped"))
    result = await harness.wrap(agent(*replies)).run("where is order 7?")
    assert result.output == "shipped"
    assert RAN == [("lookup_order", {"order_id": "7"})]
    assert pai_agents.hooks()[4:6] == ["tool.before", "tool.after"]
    with pytest.raises(RunBlocked, match="has no manifest"):
        await harness_for_test(spec()).wrap(agent(*replies)).run("where is order 7?")


async def test_approvals_escalate_but_the_apps_own_still_work() -> None:
    gated = FakeTool("lookup_order", input_schema=ORDER, governance=ALWAYS)
    replies = (calls(("lookup_order", {"order_id": "7"})), text("done"))
    with pytest.raises(RunEscalated):
        await harness_for_test(spec(), tools=[gated]).wrap(agent(*replies)).run("order 7?")
    assert RAN == []
    # A tool the app gates itself: the app answers, and the harness still governs the call.
    own = Agent(
        model(calls(("cancel_order", {"order_id": "7"})), text("done")),
        tools=[Tool(cancel_order, requires_approval=True)],
        output_type=[str, DeferredToolRequests],
    )
    harness = harness_for_test(spec(), tools=[FakeTool("cancel_order", input_schema=ORDER)])
    wrapped = harness.wrap(own)
    first = await wrapped.run("cancel 7")
    assert isinstance(first.output, DeferredToolRequests)
    answers = DeferredToolResults(approvals={c.tool_call_id: True for c in first.output.approvals})
    second = await wrapped.run(
        None, message_history=first.all_messages(), deferred_tool_results=answers
    )
    assert second.output == "done"
    assert RAN == [("cancel_order", {"order_id": "7"})]


async def test_inside_a_session_it_joins_the_run() -> None:
    harness = harness_for_test(spec(budgets={"per_run": {"max_model_calls": 1}}))
    wrapped = harness.wrap(agent(text("one")))
    async with harness.session() as session:
        assert (await wrapped.run("first")).output == "one"
        with pytest.raises(RunBlocked):
            await wrapped.run("second")  # the session's budget covers both
    assert {run for _, run in pai_agents.SEEN} == {session.run_id}
    assert "output.before" not in pai_agents.hooks()  # the session owns the output


async def test_a_session_runner_waits_for_its_agents_approvals() -> None:
    gated = FakeTool("lookup_order", input_schema=ORDER, governance=ALWAYS)
    handler = {"runner": {"use": "session", "handler": "pai_agents:ask_agent"}}
    harness = harness_for_test(spec(tasks={"t": handler}), tools=[gated])
    waiting = await harness.run("t", "where is order 7?")
    assert waiting.approval is not None
    assert RAN == []
    ops = hw.Principal(id="olga", roles=("ops",))
    done = await harness.approve(waiting.run_id, waiting.approval.approval_id, approver=ops)
    assert done.output == "shipped"  # the handler, and its agent, ran again (ADR-0021)
    assert RAN == [("lookup_order", {"order_id": "7"})]


async def test_what_wrap_refuses() -> None:
    harness = harness_for_test(spec())
    wrapped = harness.wrap(agent(text("x")))
    with pytest.raises(SpecError, match="streaming"):
        async with wrapped.run_stream("hi"):
            pass  # pragma: no cover
    with pytest.raises(UnknownProvider):
        harness.wrap(object())
    explicit = harness.wrap(agent(text("x")), adapter="pydantic_ai.agent")
    assert (await explicit.run("hi")).output == "x"
