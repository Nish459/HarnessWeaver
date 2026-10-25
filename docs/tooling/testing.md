# Testing

Everything in HarnessWeaver runs offline, against fakes, with no network and no model spend (RULES R14). The test kit, `harnessweaver.testing`, is what the framework's own tests, the examples, the templates and plugins use.

```python
import pytest
import harnessweaver as hw
from harnessweaver.testing import FakeTool, assert_trace, harness_for_test, scripted, step, text, tool_call

pytestmark = pytest.mark.anyio

SPEC = {
    "tools": {"approval_by_risk": {"high": "required"}},
    "approvals": {"approver_role": "finance"},
    "tasks": {"refund": {"runner": "direct", "output": "str", "tools": ["refund_payment"]}},
}


async def test_a_big_refund_waits_for_finance() -> None:
    refund = FakeTool("refund_payment", {"ok": True}, risk=hw.Risk.HIGH, egress=("payments.example",))
    model = scripted(tool_call("refund_payment", order_id="A-1", amount_usd=500), text("Done."))
    harness = harness_for_test(SPEC, model=model, tools=[refund])

    result = await harness.run("refund", "Refund A-1", principal="casey")

    assert result.status is hw.RunStatus.AWAITING_APPROVAL
    assert refund.calls == []                                   # nothing ran yet
    assert result.approval is not None and result.approval.approver_role == "finance"
    assert_trace(result, "run.start", "model.before", "tool.before",
                 step("tool.before", kind="note", code="approval_required"))
```

## Test mode

`HARNESSWEAVER_TEST_MODE=1` makes every live provider refuse to call out: model providers, `http` tools, webhook approval channels, remote guards, and the OTLP exporter. `harnessweaver test` sets it, and so does the repository's root `conftest.py`. A test that accidentally reaches a real model fails instead of spending money. In code, `harnessweaver.ports.network_allowed()` tells a provider whether it may call out.

Async tests use the anyio pytest plugin (`@pytest.mark.anyio`, or `pytestmark = pytest.mark.anyio`). Time comes from an injected clock, so tests never sleep (RULES T8).

## harness_for_test

```text
harness_for_test(spec=None, *, model=None, tools=(), deciders=None, clock=None, catalog=None, telemetry=None)
```

A harness for a test: offline, on a `FakeClock`, with fakes where you give them.

| Argument | Meaning |
| --- | --- |
| `spec` | A `harness.yaml` path, a spec document as a dict (`apiVersion`, `kind` and `metadata` may be left out), or a loaded spec (`hw.load_spec(...)`) |
| `model` | Replaces `models.provider`, usually a `scripted(...)` model |
| `tools` | `FakeTool`s, or any tool backend |
| `deciders` | Fake routing answers, by router name |
| `clock` | Defaults to a `FakeClock` |
| `catalog` | Where plugins are found; defaults to the installed ones |
| `telemetry` | Where spans and metrics go, for example an in-memory OpenTelemetry SDK |

```python
harness = harness_for_test({
    "guardrails": {"input": [{"use": "pii.regex", "action": "redact"}]},
    "tasks": {"echo": {"runner": "direct", "output": "str"}},
}, model=scripted("hello"))
```

To test with the org baseline, load the spec with its profiles first: `harness_for_test(hw.load_spec(SPEC, profile_dirs=[ORG]), model=...)`.

## Scripted models

`scripted(*replies, rules=(), repeat_last=True)` builds a `ScriptedModel`. Strings are text replies; the helpers build the others:

| Helper | Reply |
| --- | --- |
| `text("...")` | A text answer |
| `output({...})` | Structured output (also sent as JSON text) |
| `tool_call("name", **arguments)` | One tool call (`id=` sets its id) |
| `reply(**fields)` | Any of `text`, `output`, `tool_calls`, `usage`, `cost_usd`, `model`, `chunks`, `finish_reason`, `fail` |

```python
model = scripted(
    output({"total": "not a number"}),        # first answer: invalid, so the run repairs
    output({"total": 12.5}),
    rules=[{"contains": "refund", "reply": {"text": "Refunds take five days."}}],
)
...
assert len(model.requests) == 2                # every request the model got
```

Rules match the last message (`contains`, `matches`, `role`, `times`) before the replies are used in order. See [the scripted provider](../modules/models.md#scripted).

## Fake tools and deciders

```python
FakeTool(name, result=None, description="", input_schema={...}, side_effect=hw.SideEffect.NONE,
         risk=hw.Risk.LOW, data_access=(), egress=(), scopes=(), untrusted=True, raises=None, governance={})
```

A tool with a manifest built from its fields, so the governor treats it like a real one (`tools.require_manifest` covers it). `result` is returned, or called with the arguments; every call is kept in `.calls`; `raises` makes it fail; `governance` adds manifest fields such as `approval` or `rate_limit`.

```text
FakeDecider(choice=None, *, confidence=None, reason="fake decider")
```

A routing stage that always gives the same answer, keeping its requests in `.requests`. With no `choice` it abstains; with a `confidence` its answer is probabilistic. Pass it as `harness_for_test(..., deciders={"intent": FakeDecider("billing")})`.

## Checking traces

```python
assert_trace(result, "run.start", "input.before", "model.before", "model.after", "run.end")
assert_trace(result, step("input.before", source="guardrails.input[pii]", outcome="continue"))
assert_trace(result, step(kind="note", code="guard_fired"))
assert_trace(result, "run.start", "run.end", exact=True)   # exactly these hooks fired
```

- `assert_trace(trace, *expected, exact=False)` checks the expected events appear in order; others may come between, unless `exact`, when the strings must be exactly the hooks that fired. A failure prints the whole trace.
- A string is a hook point that fired; `step(hook, kind=..., source=..., outcome=..., code=..., band=..., reason=...)` matches any event by its fields.
- `hooks_fired(trace)` lists the hook points that fired; `render_trace(trace)` prints the trace one event per line.

## Checking for leaks

```python
from harnessweaver.testing import assert_no_content

assert_no_content([result, log_lines, span_attributes], "ann@example.com", "sk-test-123")
```

`assert_no_content(where, *values)` fails if any value appears in a result, a trace, log lines, span attributes or any mix of them: the test form of RULES R9.

## Cassettes

A `Cassette` records a real model's answers once and replays them offline, matching requests by digest:

```python
from harnessweaver.testing import Cassette

model = Cassette("tests/cassettes/extract.json", provider=real_provider, mode="auto")
harness = harness_for_test("harness.yaml", model=model)
```

| Mode | Behavior |
| --- | --- |
| `replay` | Never calls out; a request not on the cassette fails |
| `record` | Always calls out and overwrites the file |
| `auto` | Replays if the file exists, otherwise records |

`scrub=` is applied to every answer before it is saved, so secrets and personal data never reach the file (RULES S7). Recording needs the network, so run it deliberately outside test mode; in CI, cassettes only replay.

## Testing a spec's controls

The patterns the examples use:

| To check | Do |
| --- | --- |
| A guard redacts before the model | Run with a `scripted` model, then assert the redacted value isn't in `json.dumps([r.model_dump() for r in model.requests])` |
| A control blocks | Assert `result.status is hw.RunStatus.BLOCKED` and `result.error.details["code"]`, and that the model or tool was never called |
| A repair happens | Script an invalid answer then a valid one; assert two requests and a `repair` note |
| A baseline lock holds | Write an overlay that changes a locked path and expect `LockViolation` from `hw.load_spec` |
| A policy table | `harnessweaver policy test` in CI ([Tools](../modules/tools.md#dry-runs-and-policy-tests)) |
| Quality | Eval suites with baselines, `harnessweaver eval run` in CI ([Evals](../modules/evals.md)) |

## Conformance

Plugins run the shared conformance suite with `pytest --harnessweaver-conformance=<namespace>`. See [Conformance](../extending/conformance.md).

## TypeScript

`@harnessweaver/core` exports `FakeClock`, and its `load()` takes a `clock`; model calls go through the app's AI SDK model, so tests use the AI SDK's `MockLanguageModelV4` from `ai/test`. `SidecarClient` refuses to call out in test mode unless the test gives it a `fetch`. [Example 04's tests](https://github.com/Wise-DreamerZ/HarnessWeaver/tree/main/examples/04_polyglot_typescript/test) show both.
