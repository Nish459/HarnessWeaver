# Features

## HarnessWeaver features

HarnessWeaver gives you the controls every AI application needs around its models, declared in one spec and applied the same way whatever runs the model.

### Based on open standards

- [**OpenTelemetry**](https://opentelemetry.io/) spans and metrics, following the GenAI semantic conventions, so traces go to any backend you already use.
- [**JSON Schema**](https://json-schema.org/) for every contract: the spec, tool manifests, hook events, results. The schemas are generated from the Pydantic models and checked in, so editors and other languages can use them.
- [**OpenAPI**](https://www.openapis.org/) for the harnessd sidecar, so any language can generate a client.
- A safe subset of [**CEL**](https://cel.dev/) for every rule, the same in Python and TypeScript.
- **YAML 1.2** with the core schema, so `yes` and `2026-01-05` mean the same thing in every language.

### Controls in the spec

| Control | How it works | Read more |
| --- | --- | --- |
| Tracing and cost | Every run, model call, tool call and decision is traced and costed | [Observability](tutorial/observability.md) |
| Budgets and deadlines | Per-run limits on cost, tokens, model calls, tool calls and time, checked before each call | [Budgets](tutorial/budgets.md) |
| Guardrails | PII, secrets, prompt injection, size, topics, citations and LLM judges, on input, retrieved context, tool results, output and streams | [Guardrails](tutorial/guardrails.md) |
| Typed output | Pydantic validation with bounded repair, plus business rules | [Typed output](tutorial/typed-output.md), [Repairs](tutorial/validation.md) |
| Tool governance | No tool runs without a manifest, and a nine-step governor checks schema, policy, the lethal trifecta, rate limits and approvals | [Tools](tutorial/tools.md) |
| Policy and approvals | Deterministic rules decide, a person approves what they require, and runs suspend durably and resume | [Policy](tutorial/policy.md), [Approvals](tutorial/approvals.md) |
| Routing | A cascade of rules, lexical, semantic and LLM stages picks the intent, task or model | [Routing](tutorial/routing.md) |
| Retrieval governance | ACLs re-checked on every retrieved item, untrusted labels, size caps | [Retrieval](tutorial/context.md) |
| Evals | Golden sets with baselines in CI, shadow-guard reports, online sampling of production runs | [Evals](tutorial/evals.md) |
| Org baseline | Locks, bounds and a required adoption level by risk tier, enforced when an app loads | [Profiles and the org baseline](tutorial/profiles.md) |

### Keep your executor

HarnessWeaver wraps whatever your app already uses. It never asks you to rewrite an agent or switch frameworks:

- **Wrap** an OpenAI or Anthropic client, or a Pydantic AI agent, in one call: [Govern an existing client](how-to/wrap-a-client.md).
- Write your own steps in a **session**, each one governed: [Sessions](tutorial/sessions.md).
- Or let a **runner** own the task, with approvals that suspend and resume: [First steps](tutorial/first-steps.md).

### Safe by default

- **The baseline can't be removed.** An org baseline's locked controls can't be overridden, removed or reordered by any app, and a value outside a bound fails loading instead of being clamped.
- **Controls fail closed.** A baseline guard that crashes or times out blocks.
- **Nothing raw in telemetry.** Prompts, outputs and tool arguments never reach logs or spans unless the spec captures them, and then only after redaction.
- **Probabilistic components never grant.** Classifiers, LLM judges and semantic routers may route or tighten a decision, never turn a deny into an allow.
- **No silent gaps.** An unknown key, provider or hook fails loading, and so does a runner that can't reach a hook the baseline needs.

### Grow one level at a time

Each [adoption level](concepts/adoption-levels.md) is useful on its own: **L0** Observe (one line), **L1** Guard (typed output and guards), **L2** Govern (policy and tool manifests), **L3** Orchestrate (approvals and durable runs), **L4** Improve (evals in CI and production). An org baseline can require a level by risk tier.

### One spec, every language

The same `harness.yaml`, the same org baseline and the same contracts serve Python, [TypeScript](advanced/typescript.md) (with Vercel AI SDK models), and any language through the [harnessd sidecar](advanced/sidecar.md). Language-neutral conformance fixtures make the implementations agree.

### Editor support

Every spec section is a JSON Schema, so the YAML language server autocompletes and checks `harness.yaml` as you type ([The spec](concepts/spec.md#editor-support)). The Python API is fully typed and ships `py.typed`, and a misspelled key fails at load with its path and file.

### Testable

Everything runs offline, against fakes, with no network and no model spend. Test mode makes live providers refuse to call out, so a test can never spend money. The test kit gives you scripted models, fake tools, trace assertions, leak checks and cassettes ([Testing](tutorial/testing.md)), and every plugin can run the conformance suite the first-party plugins pass.

### Plugins

Anyone can write providers, middleware, routing stages, runners, adapters, profiles and templates in their own repository, under any package name, with exactly the contract the first-party plugins use ([Extending](advanced/index.md#extending-harnessweaver)).

### A small core

The core depends only on Pydantic, the OpenTelemetry API, PyYAML, anyio and loguru. Model SDKs, the OpenTelemetry SDK, sandboxes and full CEL are plugins, installed only when your spec uses them.

### Tested

The framework's own tests run offline in CI, alongside language-neutral conformance fixtures that the Python and TypeScript implementations both pass, the examples run end to end, and every template's generated project passes its own tests. The code in this documentation's tutorial is run by the test suite too.
