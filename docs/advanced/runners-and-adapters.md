# Runners, deciders and adapters

Three more kinds of contribution let a plugin change *how* work is executed or observed, without ever implementing a control itself: controls live on hook points, and these contributions only make sure the right hooks fire.

## Runners

A runner executes a task: `runner: { use: acme.flow, ... }`. The harness owns the run around it (idempotency, deadlines, `run.start`, `input.before`, `output.before`, approvals, `run.end`); the runner does the work in between, making every model and tool call through the run's context so each is governed.

```python
from collections.abc import Mapping
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, JsonValue

import harnessweaver as hw


class TwoPassConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    critique_prompt: str = Field(description="A prompt reference, 'name@version'.")


@hw.runner("two_pass", reaches=["model.before", "model.after"], config=TwoPassConfig)
class TwoPass:
    """Draft an answer, then improve it once from the model's own critique."""

    def __init__(self, config: TwoPassConfig) -> None:
        self.critique_prompt = config.critique_prompt

    async def execute(self, ctx: hw.RunContext, input: Any, resume: Mapping[str, JsonValue] | None) -> Any:
        s = hw.Session.for_run(ctx)
        draft = await s.generate(prompt="draft@1", text=str(input))
        return await s.generate(prompt=self.critique_prompt, text=str(input), draft=str(draft))
```

```yaml
tasks:
  answer:
    runner: { use: acme.two_pass, critique_prompt: critique@1 }
    output: str
```

| `@hw.runner` argument | Meaning |
| --- | --- |
| `name` | The runner's name, in the plugin's namespace |
| `reaches` | The hook points its executions fire, beyond the ones the harness fires around it. **Declare it honestly** (RULES R4): loading fails when the baseline or the budget needs a hook the runner can't reach |
| `config` | The Pydantic model of its settings |
| `contract` | The contract range it supports |
| `resumable` | Whether it can continue from a checkpoint after an approval (with `resume` holding the saved state) |
| `sample` | Settings for the conformance suite |

`execute(ctx, input, resume)` returns the task's output, and the harness fires `output.before` on it unless the run just accepted exactly that value, so a runner can't skip an output guard. There is nobody left to repair it at that point, so a `Retry` ends the run as `validation.on_failure` says; a runner that can repair checks the value itself first. `Session.for_run(ctx)` gives a session view of the run, so a runner can use `generate`, `tool`, `decide`, `context` and `prompt` like app code. The conformance suite runs every runner to a final state and checks it fires only hooks it declares (`output.before` may always fire). Runners don't plan or remember; open-ended agent behavior belongs in adapters for agent frameworks (R12).

## Deciders

A decider is a routing stage: `cascade: [{ use: acme.vip_rules }]`. The simplest form is an async function:

```python
@hw.decider("vip_rules")                          # deterministic by default
async def vip_rules(request: hw.DecisionRequest) -> hw.Decision:
    """VIP customers go straight to a person."""
    if request.state.get("tier") == "vip":
        return hw.Decision.exact("human", reason="vip customer")
    return hw.Decision.abstain()
```

| `@hw.decider` argument | Meaning |
| --- | --- |
| `name` | The stage's name, in the plugin's namespace |
| `deterministic` | Default `True`; set `False` for a model or classifier, which then may only route, never grant (R3) |
| `contract` | The contract range it supports |

A `DecisionRequest` has `router`, `text`, `options` and `state`. Answer with `Decision.exact(choice, reason=...)`, `Decision.probabilistic(choice, confidence, reason=...)` or `Decision.abstain()`. A decider with settings is a `Decider` provider class (`@hw.provider(port="Decider", ...)`) whose instances are called with the request. See [Routing](runners-and-adapters.md#deciders).

## Adapters

An adapter governs a client or framework the app already uses: `harness.instrument(client)` and `harness.wrap(agent)` find one by the target's type and return a governed stand-in.

```python
import harnessweaver as hw
from harnessweaver.adapters import Binding, CallProvider


@hw.adapter("chat", wraps=["acme_llm.Client"], reaches=["run.start", "input.before", "model.before",
                                                      "model.after", "output.before", "run.end"])
class ChatAdapter:
    """Governs acme_llm.Client.complete()."""

    def bind(self, target: "acme_llm.Client", binding: Binding) -> "GovernedClient":
        return GovernedClient(target, binding)


class GovernedClient:
    def __init__(self, client, binding: Binding) -> None:
        self._client, self._binding = client, binding

    async def complete(self, prompt: str) -> str:
        async def call(request: hw.ModelRequest) -> hw.ModelResponse:
            text = await self._client.complete(request.messages[-1].content)   # the redacted prompt
            return hw.ModelResponse(text=text)

        request = hw.ModelRequest(messages=(hw.Message(role="user", content=prompt),))
        response = await self._binding.generate(request, CallProvider(call))
        return response.text                                                    # as the hooks left it
```

| `@hw.adapter` argument | Meaning |
| --- | --- |
| `name` | The adapter's name, in the plugin's namespace |
| `wraps` | Fully qualified type names it can wrap (`"openai.AsyncOpenAI"`). `instrument()` loads the plugin whose namespace is the target's top-level package and picks the adapter that wraps its type; `adapter=` names one explicitly |
| `reaches` | The hook points one call through it fires; checked against the baseline and budget when the app wraps (R4) |
| `contract` | The contract range it supports |
| `sample` | A function returning an `AdapterSample` (an offline target and one call through it) for the conformance suite |

`bind(target, binding)` returns the stand-in. The `Binding` carries the harness, task, principal, tenant and attributes the app gave `instrument()` or `wrap()`, and `binding.generate(request, provider)` makes one governed call:

- **outside a run**, it becomes a small run of its own: `run.start`, `input.before` on the message texts, `model.before`, the call, `model.after`, `output.before` on the answer, `run.end`;
- **inside a run or session** (found through `hw.current_run()`), it is one governed model call of that run.

`CallProvider(call)` wraps the adapter's own call to the client; `call` receives the request after `model.before`, so redactions and alias changes reach the real API. Translate the client's errors into the taxonomy (`ProviderError`), and keep the framework's types out of every hook payload (R7).

### Agent frameworks

For an agent framework, one adapter object sends each of the framework's model requests through `RunContext.generate(request, provider=...)` and each tool call through `RunContext.call_tool(call, backend=...)` ([ADR-0037](../adr/0037-framework-adapters.md)), so budgets, cost, telemetry, recording and the governor apply as they do to the harness's own runners:

| `RunContext` method | Use |
| --- | --- |
| `generate(request, *, provider=None)` | One governed model call through the framework's own model |
| `call_tool(call, *, backend=None)` | One governed tool call through the framework's own tool |
| `approval_needed(call, reason, *, tool=None, approver_role=None)` | Turns an approval the framework asks for into the harness's own: returns the error that pauses the run (or escalates where it can't), matched to the call by name and arguments |
| `settle_grants()` | For a runner that runs interrupted work again: says the work so far won't run again, so the approvals it spent are gone for good ([ADR-0045](../adr/0045-what-an-approval-covers.md)). A `resumable` runner needn't call it |
| `replaying` | True during a replay. `generate` and `call_tool` then answer from the recording by themselves, ignoring `provider` and `backend`, so a replay never reaches the framework's own model or tools |

`harnessweaver-pydantic-ai` is the reference: its `HarnessCapability` does this for Pydantic AI, and its runner suspends and resumes agents with Pydantic AI's deferred tools. Read its [source](https://github.com/Wise-DreamerZ/HarnessWeaver/tree/main/python/plugins/pydantic-ai) before writing another.

The conformance suite checks that one call through an adapter fires every declared hook (except conditional ones such as `run.error`) in lifecycle order.
