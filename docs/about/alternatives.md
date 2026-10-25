# Alternatives, inspiration and comparisons

HarnessWeaver sits **around** the tools an AI application already uses. It doesn't replace them, and it is easiest to understand next to them.

## A framework, not a harness

Many teams build one central harness and route every app through it. HarnessWeaver takes the other path: it is a framework each team uses to build *its own* harness, while the platform team's baseline still applies to all of them.

| | A central harness | HarnessWeaver |
| --- | --- | --- |
| Who owns control flow | The harness | Your app, with HarnessWeaver intercepting |
| How controls are applied | Hard-wired in one runtime | Composed per app from plugins, plus an org baseline that can't be removed |
| Adopting it | Route your app through it | One line for tracing, then grow level by level |
| Languages | Usually one | Python, TypeScript, and any language through the sidecar |

## Agent frameworks

Agent frameworks, such as Pydantic AI and the Vercel AI SDK, own an app's reasoning: the prompts, the agent loop, which tool to call next. HarnessWeaver deliberately does none of that. It has no planner, memory model, prompt template language, vector store or open-ended agent loop (RULES R12). The only loop in the core is the `direct` runner's bounded tool loop.

Instead, adapters govern the frameworks: every model request, tool call and output they make passes the same hook points, guards, budgets and policy. Pydantic AI runs under the `pydantic_ai.agent` runner, or is wrapped with `harness.wrap(agent)`. Vercel AI SDK models are governed by `wrapModel` in TypeScript.

## Model gateways

A gateway such as [LiteLLM Proxy](https://docs.litellm.ai/docs/simple_proxy) holds provider keys, routes model names to providers, and owns retries, fallbacks and tenant-level budgets. HarnessWeaver works with one: `openai.chat` talks to it, reads its reported cost, and leaves retries to it, so each control has one owner (RULES R5). The harness owns what a gateway can't see: per-run budgets and deadlines, typed output and repair, guards on content, the tool governor, approvals and the trace of one run. `harnessweaver gateway litellm` generates a gateway config from the spec ([Gateways](../deployment/gateways.md)).

## Guardrail libraries

Guardrail libraries detect things in content: personal data, toxic text, prompt injection. In HarnessWeaver, a detector is a `Guardrail` **provider**: it reports what it found, and the harness decides what happens, at which stage, in which band, in shadow mode or enforced, with what fail mode. The built-in guards are deterministic and dependency-free. Model-based detectors (Presidio, Llama Guard, Prompt Guard) are *planned* as plugins, and any library can be wrapped as a provider today ([Providers and ports](../advanced/providers.md#example-a-guard)).

## Observability platforms

LLM observability platforms such as Langfuse, Phoenix and Logfire store and show traces. HarnessWeaver produces OpenTelemetry spans and metrics following the GenAI semantic conventions, so it works with any backend that reads them, and `harnessweaver dev` wires a local collector to Langfuse. It doesn't store traces itself. What it adds is the governance in them: every guard, rule, budget check and approval is a traced decision, and no content reaches a span unless the spec captures it after redaction.

## Policy engines

Policy engines such as OPA, Cedar and OpenFGA decide authorization. HarnessWeaver's policy runs at governor step 3 through a `PolicyEngine` port. The default, `cel_lite`, and `cel.policy` are built in, and engines for Cedar, OPA and OpenFGA are *planned*. Whatever the engine, the rules combine the same way, and the engine must be deterministic (RULES R3).

## Eval tools

Eval frameworks such as promptfoo, DeepEval and Ragas score model outputs. HarnessWeaver's evals run the **whole task**, with its guards, rules, tools and policy, grade it with deterministic graders or an LLM judge, compare with a committed baseline in CI, and sample production runs. Graders are an `Evaluator` port, so other frameworks' metrics can plug in. Adapters for them are *planned*.

## Durable execution

Workflow engines such as Temporal and DBOS make long-running code durable. HarnessWeaver's durability is deliberately smaller: a run that waits for a person is checkpointed in the state store and resumed from there ([ADR-0009](../adr/0009-durability-checkpoints.md)). Runners on Temporal or DBOS are *planned*. HarnessWeaver will never build a scheduler of its own.

## Inspiration

The closest analogies are **OpenTelemetry**, with a tiny stable API, swappable implementations and contributed integrations, and **Spring Boot**, with starters and opinionated defaults that work with no configuration and can be overridden piece by piece. The structure of this documentation follows [FastAPI](https://fastapi.tiangolo.com/)'s ([ADR-0042](../adr/0042-docs-structure.md)).
