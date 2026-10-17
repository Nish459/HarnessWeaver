"""Python runners for the runtime suites: ``bus``, ``budgets`` and ``plugins``."""

from datetime import timedelta
from typing import Any

import anyio
import pytest

from harnessweaver.core.budgets import BudgetMeter, resolve_cost
from harnessweaver.core.bus import HookBus
from harnessweaver.core.envelope import Budget, Envelope, FakeClock
from harnessweaver.core.errors import SpecError
from harnessweaver.core.hooks import Band, HookPoint, InputEvent, OutputEvent, RunEndEvent
from harnessweaver.core.messages import Message, ModelRequest, ModelResponse, Usage
from harnessweaver.core.middleware import Registration, middleware
from harnessweaver.core.outcomes import Block, Continue, Escalate, Outcome, Retry, Suspend
from harnessweaver.core.plugins import Contribution, Plugin, check_owned, qualify
from harnessweaver.core.registry import is_allowed, owner_of
from harnessweaver.core.runs import RunStatus
from harnessweaver.core.trace import RunTrace, TraceKind

from .test_suites import _strict_equal

# --- bus -----------------------------------------------------------------------------------------


def _event(hook: HookPoint, value: Any) -> Any:
    if hook is HookPoint.INPUT_BEFORE:
        return InputEvent(input=value)
    if hook is HookPoint.OUTPUT_BEFORE:
        return OutputEvent(output=value)
    return RunEndEvent(status=RunStatus.COMPLETED, output=value)


def _value(event: Any) -> Any:
    return event.input if isinstance(event, InputEvent) else event.output


def _answer(does: dict[str, Any], event: Any) -> Any:
    match does["outcome"]:
        case "continue":
            return Continue()
        case "modify":
            hook = HookPoint(event.hook)
            return Continue(modified=_event(hook, does["value"]).model_copy(update={}))
        case "retry":
            return Retry(reason=does["reason"])
        case "escalate":
            return Escalate(reason=does["reason"])
        case "suspend":
            return Suspend(reason=does["reason"])
        case "block":
            return Block(reason=does["reason"], code=does["code"])
        case "bad_answer":
            return "yes"
        case "bad_modify":
            other = (
                HookPoint.OUTPUT_BEFORE if event.hook != "output.before" else HookPoint.INPUT_BEFORE
            )
            return Continue(modified=_event(other, "x"))
        case unknown:
            raise AssertionError(f"unknown behavior {unknown}")


def _registration(spec: dict[str, Any], hook: HookPoint, handler: Any) -> Registration:
    timed = spec["does"]["outcome"] == "timeout"
    return Registration(
        name=spec["name"],
        handler=handler,
        hooks=frozenset({hook}),
        band=Band(spec["band"]),
        fail_mode=spec["fail_mode"],
        timeout=timedelta(milliseconds=10) if timed else None,
    )


@pytest.mark.conformance_suite("bus")
@pytest.mark.anyio
async def test_bus(case: dict[str, Any]) -> None:
    hook = HookPoint(case["hook"])
    expect = case["expect"]
    ran: list[str] = []
    seen: dict[str, Any] = {}

    def handler_for(spec: dict[str, Any]) -> Any:
        async def handler(event: Any, env: Envelope) -> Outcome | None:
            ran.append(spec["name"])
            seen[spec["name"]] = _value(event)
            match spec["does"]["outcome"]:
                case "raise":
                    raise RuntimeError("scripted failure")
                case "timeout":
                    await anyio.Event().wait()
                case _:
                    pass
            return _answer(spec["does"], event)

        return handler

    registrations = [_registration(spec, hook, handler_for(spec)) for spec in case["middleware"]]
    if "error" in expect:
        with pytest.raises(SpecError) as caught:
            HookBus(registrations)
        assert caught.value.code.value == expect["error"]
        return
    bus = HookBus(registrations)

    clock = FakeClock()
    trace = RunTrace(clock)
    env = Envelope.new(tenant="t", principal="p", clock=clock)
    result = await bus.emit(hook, _event(hook, case["value"]), env, trace)

    outcome = expect["outcome"]
    assert result.outcome.kind == outcome["kind"]
    if "modified" in outcome:
        assert isinstance(result.outcome, Continue)
        assert (result.outcome.modified is not None) is outcome["modified"]
    if "reason" in outcome:
        assert getattr(result.outcome, "reason", None) == outcome["reason"]
    if "code" in outcome:
        assert getattr(result.outcome, "code", None) == outcome["code"]
    assert ran == expect["ran"]
    for name, value in expect.get("seen", {}).items():
        assert seen[name] == value, name
    assert _value(result.event) == expect["value"]
    recorded = [
        [e.source, e.kind.value, e.outcome.value if e.outcome else None, e.modified]
        for e in trace
        if e.kind in (TraceKind.OUTCOME, TraceKind.FAILURE)
    ]
    assert recorded == expect["trace"]
    hook_events = [e for e in trace if e.kind is TraceKind.HOOK]
    assert len(hook_events) == 1
    assert hook_events[0].outcome is not None
    assert hook_events[0].outcome.value == outcome["kind"]


# --- budgets -------------------------------------------------------------------------------------


@pytest.mark.conformance_suite("budgets")
def test_budgets(case: dict[str, Any]) -> None:
    expect = case["expect"]
    if "cost" in case:
        given = case["cost"]
        prices = {name: (pair[0], pair[1]) for name, pair in given["prices"].items()}
        usd, source = resolve_cost(
            ModelResponse.model_validate(given["response"]),
            ModelRequest(messages=(Message.user("x"),), **given["request"]),
            prices.get if prices else None,
        )
        assert source == expect["source"]
        if expect["usd"] is None:
            assert usd is None
        else:
            assert usd == pytest.approx(expect["usd"], rel=1e-12, abs=1e-12)
        return

    meter = BudgetMeter(Budget.model_validate(case["limits"]))
    results: list[str | None] = []
    for op in case["ops"]:
        match op["op"]:
            case "model.before":
                request = ModelRequest(messages=(Message.user("a" * op["chars"]),))
                limit = meter.check_model_call(request)
                if limit is None:
                    meter.start_model_call()
            case "model.after":
                limit = meter.record_model_call(Usage.model_validate(op["usage"]), op["cost_usd"])
            case "tool.before":
                limit = meter.check_tool_call()
                if limit is None:
                    meter.start_tool_call()
            case unknown:
                raise AssertionError(f"unknown op {unknown}")
        results.append(limit)
    assert results == expect["results"]
    want = expect["meter"]
    assert meter.usd == pytest.approx(want["usd"], rel=1e-12, abs=1e-12)
    assert meter.cost_known is want["cost_known"]
    assert meter.usage.input_tokens == want["input_tokens"]
    assert meter.usage.output_tokens == want["output_tokens"]
    assert meter.model_calls == want["model_calls"]
    assert meter.tool_calls == want["tool_calls"]
    if "remaining" in expect:
        left = meter.remaining().model_dump(exclude={"deadline"})
        for key, value in expect["remaining"].items():
            assert left[key] == pytest.approx(value), key


# --- plugins -------------------------------------------------------------------------------------


@pytest.mark.conformance_suite("plugins")
def test_plugins(case: dict[str, Any]) -> None:
    expect = case["expect"]
    if "owner_of" in case:
        assert owner_of(case["owner_of"]) == expect
    elif "qualify" in case:
        namespace, name = case["qualify"]
        assert qualify(namespace, name) == expect
    elif "owns" in case:
        namespace, name = case["owns"]

        @middleware(hooks=["run.start"], fail_mode="closed")
        async def item(event: Any, env: Envelope) -> None:
            return None

        contribution = Contribution("middleware", name, None, item)
        problem = check_owned(Plugin(namespace=namespace, version="1.0.0"), contribution)
        assert _strict_equal(problem is None, expect)
    elif "allowed" in case:
        namespace, allow = case["allowed"]
        assert _strict_equal(is_allowed(namespace, allow), expect)
    else:
        try:
            Plugin(namespace=case["namespace"], version="1.0.0")
        except ValueError:
            valid = False
        else:
            valid = True
        assert valid is expect
