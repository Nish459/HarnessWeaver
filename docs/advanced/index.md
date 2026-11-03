# Advanced guide

The [Tutorial](../tutorial/index.md) is enough to build a complete, governed app. This guide covers the rest: how specs merge in detail, the tool governor and approvals in depth, other languages, and extending HarnessWeaver with your own plugins.

!!! tip
    Read the tutorial first. These pages build on it and assume you know its words: spec, overlay, task, runner, session, guard, hook point.

## In depth

| Page | Covers |
| --- | --- |
| [Layers, locks and bounds](layers.md) | Every merge rule, lock form and bound, profile references and version ranges, provenance |
| [The tool governor](governor.md) | The nine steps, the lethal trifecta, schema validation, idempotency, dry runs, sandboxed code |
| [Approvals in depth](approvals.md) | Requests, grants, how each runner resumes, crash safety, background runs |

## Other languages

| Page | Covers |
| --- | --- |
| [TypeScript](typescript.md) | `@harnessweaver/core` and `@harnessweaver/ai-sdk`: the same spec in TypeScript apps, with Vercel AI SDK models |
| [harnessd sidecar](sidecar.md) | The spec served over HTTP, for any language |

## Extending HarnessWeaver

> **A module becomes a plugin by how it is designed, not by what it is called.**

HarnessWeaver ships the plugins most apps need: model providers, the Pydantic AI adapter, a sandbox, OpenTelemetry export and full CEL. Anyone can build more, **in their own repository, under any package name**, and use them with no change to HarnessWeaver. First-party and third-party plugins use exactly the same contract. The plugins in this repository get no private hooks into the core, and the core registers its own built-in providers through that contract too.

### What you can add

| Contribution | Declared with | Selected in the spec by | Page |
| --- | --- | --- | --- |
| A provider for any port (`Guardrail`, `PolicyEngine`, `ModelProvider`, `ContextProvider`, `Sandbox`, `Evaluator`, ...) | `@hw.provider` | `use: acme.pii` in the module's section | [Providers and ports](providers.md) |
| Middleware on any hook point | `@hw.middleware` | `middleware: [{ use: acme.no_weekend_refunds }]` | [Middleware](middleware.md) |
| A routing stage | `@hw.decider` | `cascade: [{ use: acme.vip_rules }]` | [Runners, deciders and adapters](runners-and-adapters.md#deciders) |
| A runner | `@hw.runner` | `tasks.<t>.runner: { use: acme.flow }` | [Runners, deciders and adapters](runners-and-adapters.md#runners) |
| An adapter for a client or agent framework | `@hw.adapter` | Picked by `harness.instrument()` or `harness.wrap()` from the target's type | [Runners, deciders and adapters](runners-and-adapters.md#adapters) |
| Profiles | `hw.Plugin(profiles={...})` | `extends: ["profile://acme.baseline@^1"]` | [Plugins](plugins.md#profiles-and-templates) |
| Project templates | `hw.Plugin(templates={...})` | `harnessweaver init -t acme.rag` | [Plugins](plugins.md#profiles-and-templates) |

### The public extension surface

Build only against these. They are versioned with the contract (RULES V1, V2), so a plugin keeps working across core releases within `harnessweaver/v1`:

- `harnessweaver.Plugin` and the decorators `provider`, `middleware`, `decider`, `runner`, `adapter`;
- the port Protocols in `harnessweaver.ports`;
- the contract models exported from `harnessweaver` (events, outcomes, `GuardResult`, `Decision`, `ModelRequest`, `ToolResult`, ...);
- `harnessweaver.adapters` (`Binding`, `CallProvider`), for adapters;
- `harnessweaver.testing`, including the conformance suite.

Anything else, and every module whose name starts with `_`, is internal and may change (RULES C7). The [Python API reference](../reference/python/index.md) documents this surface.

### The rules plugins live by

- **Installing is not enabling.** Installing a plugin activates nothing. Only names the effective spec refers to are imported, and plugin modules must do no I/O and register nothing at import time (RULES S8).
- **The spec assigns bands, not the plugin.** A plugin can't put its middleware in the `baseline` band; only an org profile can (R1, R2).
- **Orgs decide what's allowed.** A baseline can lock `plugins.allow` to a list of namespaces.
- **Contracts are declared.** Every plugin and contribution declares the contract range it was built against (`>=1.0,<2`), and the loader refuses an incompatible one (V5).
- **Conformance is shared.** Every plugin can run the same conformance suite the first-party plugins pass (T5).
- **No framework types in contracts.** Hook payloads, ports and results hold only HarnessWeaver types (R7).
- **Probabilistic components never grant** (R3): a judge or classifier can only tighten a decision.

### Start here

1. `uv run harnessweaver plugin new acme` scaffolds a standalone package with a sample guard and tests that run the conformance suite.
2. Read [Plugins](plugins.md) for packaging, namespaces and loading.
3. Pick the contribution you need from the table above.
4. Run `pytest --harnessweaver-conformance=acme` ([Conformance](conformance.md)).
5. Publish it under any name. Apps add the package and write `use: acme.<name>`.

For TypeScript plugins, see [TypeScript](typescript.md#plugins).
