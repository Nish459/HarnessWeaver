# Alternatives and comparisons

HarnessWeaver puts controls around the model calls, tool calls and outputs of an app that already has an executor. Several products cover part of that. This page names them and says how HarnessWeaver differs from each.

| Product | What it does | How HarnessWeaver differs |
| --- | --- | --- |
| NeMo Guardrails | Programmable rails for an LLM app: input, dialog, retrieval, execution and output, configured in YAML and Colang | No dialog flows. One spec also holds budgets, typed output, tool governance, approvals and evals, under an org baseline apps can't remove |
| Guardrails AI | Validators from the Guardrails Hub, combined into input and output guards | A detector is one provider. The spec decides what happens when it fires, where, and whether it enforces |
| LangChain middleware, OpenAI Agents SDK guardrails | Controls built into one agent framework, written in the app's code | One spec for every executor and language, and a platform baseline that applies whatever the app's code does |
| LiteLLM Proxy | A model gateway: provider keys, routing, retries, fallbacks, tenant budgets | Works with the gateway, and owns what it can't see: per-run budgets, typed output, guards on content, tools and approvals |
| Langfuse, Phoenix, Logfire | Store and show LLM traces | Produces the traces through OpenTelemetry, and doesn't store them |
| OPA, Cedar, OpenFGA | Authorization policy engines | Policy is one step of the tool governor. Engines for these are *planned* |
| promptfoo, DeepEval, Ragas | Score model outputs | Evals run the whole governed task, with baselines in CI |
| Temporal, DBOS | Durable workflow execution | Only a run that waits for a person is checkpointed. Runners on these are *planned* |

## A framework, not a central harness

Many teams build one central harness and route every app through it. HarnessWeaver is a framework each team uses to build *its own* harness, while the platform team's baseline still applies to all of them.

| | A central harness | HarnessWeaver |
| --- | --- | --- |
| Who owns control flow | The harness | Your app, with HarnessWeaver intercepting |
| How controls are applied | Hard-wired in one runtime | Composed per app from plugins, plus an org baseline that can't be removed |
| Adopting it | Route your app through it | One line for tracing, then grow level by level |
| Languages | Usually one | Python, TypeScript, and any language through the sidecar |

## Guardrail frameworks

These are the closest alternatives.

**NeMo Guardrails** adds programmable rails to an LLM app: input rails on the user's message, dialog rails that steer the conversation with Colang flows, retrieval rails on retrieved chunks, execution rails on tool calls, and output rails on the answer. HarnessWeaver has no dialog rails or flow language, because it never decides what the conversation says next (RULES R12). Its guards run at the same places (input, retrieved context, tool results, output and streams), and the same spec also holds budgets and deadlines, typed output with repair, tool manifests and the governor, policy, approvals and evals. A platform team's baseline is merged into every app's spec, and no app can remove its locked controls.

**Guardrails AI** combines validators from the Guardrails Hub into input and output guards around a model call, and can run them as a server that apps call. In HarnessWeaver a detector is a `Guardrail` **provider**: it reports what it found, and the spec decides what happens, at which stage, in which band, in shadow mode or enforced, and with what fail mode. The built-in guards are deterministic and need no dependencies. Model-based detectors (Presidio, Llama Guard, Prompt Guard) are *planned* as plugins, and any validator library can be wrapped as a provider today ([Providers and ports](../advanced/providers.md#example-a-guard)).

## Agent frameworks

Agent frameworks, such as Pydantic AI, LangChain and the Vercel AI SDK, own an app's reasoning: the prompts, the agent loop, which tool to call next. HarnessWeaver does none of that. It has no planner, memory model, prompt template language, vector store or open-ended agent loop (RULES R12). The only loop in the core is the `direct` runner's bounded tool loop.

Some agent frameworks have controls of their own. LangChain agents take middleware that redacts personal data before the model sees it, asks a person to approve a tool call, or runs before each model call and around each tool call. The OpenAI Agents SDK has input, output and tool guardrails whose tripwires stop the run. These controls live in the app's code and work inside that one framework. HarnessWeaver's controls live in a spec that applies the same way to raw SDK calls, to the frameworks it has adapters for, and to other languages, and the org baseline applies whether or not the app's code asks for it.

Adapters govern the frameworks: every model request, tool call and output they make passes the same hook points, guards, budgets and policy. Pydantic AI runs under the `pydantic_ai.agent` runner, or is wrapped with `harness.wrap(agent)`. Vercel AI SDK models are governed by `wrapModel` in TypeScript. Adapters for LangGraph and the OpenAI Agents SDK are *planned*.

## Model gateways

A gateway such as [LiteLLM Proxy](https://docs.litellm.ai/docs/simple_proxy) holds provider keys, routes model names to providers, and owns retries, fallbacks and tenant-level budgets. HarnessWeaver works with one: `openai.chat` talks to it, reads its reported cost, and leaves retries to it, so each control has one owner (RULES R5). The harness owns what a gateway can't see: per-run budgets and deadlines, typed output and repair, guards on content, the tool governor, approvals and the trace of one run. `harnessweaver gateway litellm` generates a gateway config from the spec ([Gateways](../deployment/gateways.md)).

## Observability platforms

LLM observability platforms such as Langfuse, Phoenix and Logfire store and show traces. HarnessWeaver produces OpenTelemetry spans and metrics following the GenAI semantic conventions, so it works with any backend that reads them, and `harnessweaver dev` wires a local collector to Langfuse. It doesn't store traces itself. What it adds is the governance in them: every guard, rule, budget check and approval is a traced decision, and no content reaches a span unless the spec captures it after redaction.

## Policy engines

Policy engines such as OPA, Cedar and OpenFGA decide authorization. HarnessWeaver's policy runs at governor step 3 through a `PolicyEngine` port. The default, `cel_lite`, and `cel.policy` are built in, and engines for Cedar, OPA and OpenFGA are *planned*. Whatever the engine, the rules combine the same way, and the engine must be deterministic (RULES R3).

## Eval tools

Eval frameworks such as promptfoo, DeepEval and Ragas score model outputs. HarnessWeaver's evals run the **whole task**, with its guards, rules, tools and policy, grade it with deterministic graders or an LLM judge, compare with a committed baseline in CI, and sample production runs. Graders are an `Evaluator` port, so other frameworks' metrics can plug in. Adapters for them are *planned*.

## Durable execution

Workflow engines such as Temporal and DBOS make long-running code durable. HarnessWeaver's durability is smaller: a run that waits for a person is checkpointed in the state store and resumed from there. Runners on Temporal or DBOS are *planned*. HarnessWeaver won't build a scheduler of its own.
