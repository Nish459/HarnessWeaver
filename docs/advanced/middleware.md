# Middleware

Middleware is the most direct way to add behavior: an async function attached to hook points that answers each event with an outcome. Guardrails, validation rules and routers are all installed as middleware; your own middleware runs on the same bus, under the same ordering rules ([The hook bus](../concepts/hook-bus.md)).

```python
import harnessweaver as hw


@hw.middleware(hooks=["tool.before"], band="app", fail_mode="closed", timeout="1s")
async def no_weekend_refunds(event: hw.ToolCallEvent, env: hw.Envelope) -> hw.Outcome | None:
    """Refunds asked for at the weekend wait for someone in finance."""
    if event.tool.name == "refund_payment" and env.clock.is_weekend() and event.approval is None:
        return hw.Suspend(reason="weekend refunds need approval", approver_role="finance")
    return None
```

## The decorator

| Argument | Meaning |
| --- | --- |
| `hooks` | The hook points it attaches to (`"tool.before"`, or `hw.HookPoint` values) |
| `fail_mode` | Required: `closed` turns a raise or timeout into `Block` (`middleware_error`, `middleware_timeout`); `open` records it and continues ([ADR-0014](../adr/0014-required-fail-mode.md)) |
| `band` | The default band (`app`); the spec item decides, and only profiles may use `baseline` |
| `timeout` | A duration or seconds; none by default |
| `name` | Defaults to the function's name, or a class's name in snake case; lowercase words and `_` |
| `config` | For a class middleware: the Pydantic model of its settings |
| `sample` | Settings for the conformance suite, when `config` has required fields |

The function must be async. It receives the hook's event and the run's envelope.

## Answering

| Return | Effect |
| --- | --- |
| `None` or `hw.Continue()` | Proceed unchanged |
| `hw.Continue(modified=event.model_copy(update={...}))` | Proceed with a changed event; later middleware and the operation see it |
| `hw.Retry(reason)` | Redo the step: honored at `model.after` and `output.before` |
| `hw.Escalate(reason, to=...)` | Hand the run to a human queue |
| `hw.Suspend(reason, approver_role=...)` | Pause for approval: at `tool.before` and `output.before` in a harness-driven run; it escalates elsewhere |
| `hw.Block(reason, code=...)` | Refuse; give a stable `code` so tests, evals and dashboards can match it |

Never raise to control the run: return an outcome. A modified event must be the same type as the one received. Reasons and codes must never contain content (R9).

```python
@hw.middleware(hooks=["input.before"], fail_mode="closed")
async def strip_signatures(event: hw.InputEvent, env: hw.Envelope) -> hw.Outcome | None:
    """Drop e-mail signatures before anything else sees the input."""
    if isinstance(event.input, str) and "\n-- \n" in event.input:
        return hw.Continue(modified=event.model_copy(update={"input": event.input.split("\n-- \n")[0]}))
    return None
```

## Middleware with settings

```python
from pydantic import BaseModel, ConfigDict


class CapSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")
    max_usd: float


@hw.middleware(hooks=["tool.before"], fail_mode="closed", config=CapSettings)
class RefundCap:
    """Blocks refunds above a cap the spec sets."""

    def __init__(self, config: CapSettings) -> None:
        self.max_usd = config.max_usd

    async def __call__(self, event: hw.ToolCallEvent, env: hw.Envelope) -> hw.Outcome | None:
        amount = event.call.arguments.get("amount_usd", 0)
        if event.tool.name == "refund_payment" and isinstance(amount, int | float) and amount > self.max_usd:
            return hw.Block(reason="over the refund cap", code="refund_cap")
        return None
```

## In the spec

```yaml
plugins:
  local: ["app.harness_plugin"]          # or install the plugin package
middleware:
  - { use: acme.no_weekend_refunds }
  - { id: cap, use: acme.refund_cap, max_usd: 500, timeout: 500ms }
  - { use: acme.audit, hooks: [run.end], fail_mode: open }   # narrow the hooks; let an audit failure pass
```

| Key | Meaning |
| --- | --- |
| `use` | The middleware's full name |
| `id` | Names the item for merges and locks (`middleware[cap]`); default `<use>#<n>` |
| `band` | Defaults to the declaring layer's band; only profiles may set `baseline` |
| `hooks` | Narrow the hook points; it can't attach to a hook it doesn't declare |
| `fail_mode`, `timeout` | Override the declared ones; baseline middleware must stay `closed` |
| `enabled` | `false` switches it off (not allowed on a locked item) |
| *other keys* | Settings for a class middleware's `config` |

`middleware` is a keyed list, so a later layer can change an item by restating its `id`, and a profile can lock it (`middleware[cap]`).

## Testing middleware

Test the outcome and the trace, and the failure path for its fail mode:

```python
async def test_weekend_refunds_wait() -> None:
    harness = harness_for_test(spec, model=scripted(tool_call("refund_payment", amount_usd=20), text("ok")),
                               tools=[FakeTool("refund_payment")], clock=FakeClock(saturday))
    result = await harness.run("refund", "refund please", principal="casey")
    assert result.status is hw.RunStatus.AWAITING_APPROVAL
    assert_trace(result, step("tool.before", source="acme.no_weekend_refunds", outcome="suspend"))
```

The conformance suite also calls every middleware with a sample event for each hook it declares and checks it answers with an outcome, never by raising ([Conformance](conformance.md)).

## TypeScript

`defineMiddleware({ name, hooks, fail_mode, band, timeout, handler })`, registered through `definePlugin` ([TypeScript](typescript.md#plugins)).
