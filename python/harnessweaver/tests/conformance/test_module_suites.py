"""Python runners for the module suites: ``guards``."""

from typing import Any

import pytest

from harnessweaver.core.budgets import BudgetMeter
from harnessweaver.core.bus import HookBus
from harnessweaver.core.context import RunContext
from harnessweaver.core.envelope import Envelope, FakeClock
from harnessweaver.core.guards import GuardAction
from harnessweaver.core.hooks import (
    Band,
    ContextEvent,
    InputEvent,
    OutputEvent,
    StreamChunkEvent,
    ToolResultEvent,
)
from harnessweaver.core.messages import Message, ModelRequest, StreamChunk, ToolCall
from harnessweaver.core.middleware import Registration
from harnessweaver.core.registry import PluginCatalog, Registry
from harnessweaver.core.retrieval import ContextItem
from harnessweaver.core.tools import ToolInfo, ToolResult
from harnessweaver.core.trace import RunTrace
from harnessweaver.modules.guardrails import STAGE_HOOKS, Guard, guard_handler

REGISTRY = Registry(PluginCatalog())


def _env() -> Envelope:
    return Envelope.new(tenant="t", principal="p", clock=FakeClock())


def _event(stage: str, content: Any) -> Any:
    match stage:
        case "input":
            return InputEvent(input=content)
        case "output":
            return OutputEvent(output=content)
        case "tool_result":
            call = ToolCall(id="c1", name="lookup")
            result = ToolResult(call_id="c1", output=content)
            return ToolResultEvent(call=call, tool=ToolInfo(name="lookup"), result=result)
        case "stream":
            request = ModelRequest(messages=(Message.user("q"),))
            return StreamChunkEvent(request=request, chunk=StreamChunk(index=0, delta=content))
        case _:
            items = tuple(ContextItem(id=i, content=text, source="kb") for i, text in content)
            return ContextEvent(source="kb", items=items)


def _content(stage: str, event: Any) -> Any:
    match stage:
        case "input":
            return event.input
        case "output":
            return event.output
        case "tool_result":
            return event.result.output
        case "stream":
            return event.chunk.delta
        case _:
            return [[item.id, item.content] for item in event.items]


def _guard(spec: dict[str, Any]) -> Guard:
    provider = REGISTRY.provider("Guardrail", spec["use"]).build(spec.get("config", {}))
    action = GuardAction(spec["action"]) if "action" in spec else None
    return Guard(id=spec["id"], provider=provider, action=action, mode=spec.get("mode", "enforce"))


@pytest.mark.conformance_suite("guards")
@pytest.mark.anyio
async def test_guards(case: dict[str, Any]) -> None:
    expect = case["expect"]
    if "guard" in case:
        provider = REGISTRY.provider("Guardrail", case["guard"]).build(case.get("config", {}))
        if "context_ids" in case:
            env = _env()
            run = RunContext(
                envelope=env,
                bus=HookBus(),
                trace=RunTrace(env.clock),
                meter=BudgetMeter(env.budget),
                context_ids=case["context_ids"],
            )
            with run.activate():
                result = await provider.check(case["content"], env)
        else:
            result = await provider.check(case["content"], _env())
        assert result.action.value == expect["action"]
        assert result.content == expect["content"]
        assert sorted({f.type for f in result.findings}) == expect["findings"]
        if "score" in expect:
            assert result.score == pytest.approx(expect["score"])
        return

    stage = case["stage"]
    groups: list[list[dict[str, Any]]] = []
    for spec in case["guards"]:
        if spec.get("parallel") and groups and groups[-1][-1].get("parallel"):
            groups[-1].append(spec)
        else:
            groups.append([spec])
    bus = HookBus()
    for group in groups:
        guards = [_guard(spec) for spec in group]
        label = "+".join(g.id for g in guards)
        bus.add(
            Registration(
                name=label,
                handler=guard_handler(stage, guards, label),
                hooks=frozenset({STAGE_HOOKS[stage]}),
                band=Band.APP,
                fail_mode="closed",
            )
        )
    trace = RunTrace(FakeClock())
    result = await bus.emit(STAGE_HOOKS[stage], _event(stage, case["content"]), _env(), trace)
    assert result.outcome.kind == expect["outcome"]
    assert _content(stage, result.event) == expect["content"]
    if "note" in expect:
        assert any(expect["note"] in (e.reason or "") for e in trace), [e.reason for e in trace]
