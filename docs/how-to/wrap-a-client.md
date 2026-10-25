# Govern an existing client

You don't need tasks to start. An app that already calls a model through the OpenAI or Anthropic SDK can be governed in three lines, without changing the code that uses the client. Every call is then traced, costed, budgeted and guarded. That is adoption level **L0** ([Adoption levels](../concepts/adoption-levels.md)).

## The three lines

```python
import harnessweaver as hw                                    # 1

harness = hw.load("harness.yaml")                             # 2
client = harness.instrument(AsyncOpenAI(base_url=GATEWAY))    # 3
# The rest of the app uses `client` exactly as before.
```

## A complete example

[Example 01](../resources/examples.md#example-01-invoice-extraction) runs this offline. Its spec has no tasks, just the extraction profile's guards and a budget:

```yaml title="instrument.yaml"
--8<-- "examples/01_invoice_extraction/instrument.yaml"
```

And the app instruments the client it already has:

```python title="l0_instrument.py (excerpt)"
--8<-- "examples/01_invoice_extraction/l0_instrument.py:59:76"
```

```console
$ HARNESSWEAVER_ENV=offline uv run python examples/01_invoice_extraction/l0_instrument.py
invoice: INV-2026-0042, total 1860.00 EUR
the gateway saw: Billed to: Acme Corp, [EMAIL]
the gateway saw: Questions? Call [PHONE]
```

The app's call is unchanged. The PII guard redacted the customer's details before the request left the process, so the gateway saw only placeholders, and the answer was checked for secrets before the app got it.

## What instrument does

- `harness.instrument(client)` finds an adapter from the client's type: it loads the plugin whose namespace is the client's top-level package (`openai`, `anthropic`) and asks it for an adapter. `adapter=` names one explicitly.
- It governs `chat.completions.create` on `openai.OpenAI` and `AsyncOpenAI`, and `messages.create` on `anthropic.Anthropic` and `AsyncAnthropic`. Other methods pass through.
- **Outside a run**, each call becomes a small run of its own: `run.start`, `input.before` on the message texts, `model.before`, `model.after`, `output.before` on the answer, `run.end`. So the budget, the guards and the trace apply per call.
- **Inside a run or session**, a call is one governed model call of that run.
- Redactions are written back: the API receives the redacted request, and the app gets the answer as the output guards left it.
- If the baseline or the budget needs a hook the adapter can't reach, `instrument()` fails instead of running ungoverned (RULES R4).
- Streaming through an instrumented client is *planned*. Until then it raises, rather than running ungoverned.

Pass `tenant=` and `task=` to say whom the calls act for, and which task's budget and guards apply:

```python
client = harness.instrument(AsyncOpenAI(base_url=GATEWAY), tenant="acme", task="triage")
```

## Agent frameworks

`harness.wrap(agent, task=...)` does the same for an agent from another framework. For Pydantic AI it governs every model request, tool call and the final output ([ADR-0037](../adr/0037-framework-adapters.md)). A call that needs approval escalates, because the harness can't resume the app's code. To get approvals that suspend and resume, run the agent as a task with the `pydantic_ai.agent` runner instead ([Runners, deciders and adapters](../advanced/runners-and-adapters.md#agent-frameworks)).

## Next steps

Once calls are governed, move the work that matters into tasks one at a time: [typed output](../tutorial/typed-output.md) gets you to L1, [policy](../tutorial/policy.md) to L2. [Integration styles](../concepts/integration-styles.md) compares Wrap, Session and Run.
