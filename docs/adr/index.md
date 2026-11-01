# Architecture decision records

Each architecture decision record (ADR) states a decision HarnessWeaver made, why, and its status. They are the reasoning behind the design in [DESIGNS.md](https://github.com/Wise-DreamerZ/HarnessWeaver/blob/main/DESIGNS.md), which indexes them in its No. 28, and many of them record where the framework departs from the original [design guide](https://github.com/Wise-DreamerZ/HarnessWeaver/blob/main/docs/AI%20Harness%20Framework%20Design%20and%20Build%20Guide.md).

- **When an ADR is needed:** for a new module or port, a new dependency (RULES C10), a change to a contract that isn't additive (V2), an exception to a rule, or any decision a future contributor would otherwise have to rediscover.
- **How it is written:** a short decision and its reason, in a new file `docs/adr/NNNN-slug.md`, with a row in DESIGNS.md No. 28. See [Contributing](../resources/contributing.md).
- **Changing a decision:** a new ADR supersedes the old one, whose status then says so. Accepted ADRs aren't rewritten.

| ADR | Decision | Status |
| --- | --- | --- |
| [ADR-0001](0001-ship-as-harnessweaver.md) | Ship as HarnessWeaver | Accepted |
| [ADR-0002](0002-python-312.md) | Support Python 3.12 and later | Accepted |
| [ADR-0003](0003-core-dependencies.md) | The core's dependencies | Accepted |
| [ADR-0004](0004-cel-lite.md) | cel-lite, the built-in expression language | Accepted |
| [ADR-0005](0005-contracts-from-pydantic.md) | Contracts are Pydantic models; schemas are generated | Accepted |
| [ADR-0006](0006-workspace-packages.md) | One uv workspace of separate packages | Accepted |
| [ADR-0007](0007-sidecar-http-first.md) | The sidecar speaks HTTP/JSON first | Accepted |
| [ADR-0008](0008-guard-modes.md) | Spec guards enforce by default; the CLI scaffolds shadow guards | Accepted |
| [ADR-0009](0009-durability-checkpoints.md) | Durability starts as state-store checkpoints | Accepted |
| [ADR-0010](0010-otel-api-only.md) | The core uses only the OpenTelemetry API | Accepted |
| [ADR-0011](0011-bounded-tool-loop.md) | The direct runner's bounded tool loop | Accepted |
| [ADR-0012](0012-no-price-table.md) | No built-in price table | Accepted |
| [ADR-0013](0013-prompts-without-templates.md) | Versioned prompts without a template language | Accepted |
| [ADR-0014](0014-required-fail-mode.md) | A middleware's fail_mode is required | Accepted |
| [ADR-0015](0015-plugins-by-design.md) | Plugins are defined by design, not by name | Accepted |
| [ADR-0016](0016-non-core-dependencies.md) | Dependencies outside the core | Accepted |
| [ADR-0017](0017-yaml-1-2.md) | Specs are YAML 1.2 (core schema) | Accepted |
| [ADR-0018](0018-locks-and-bounds.md) | Locks forbid changes, not restatements; bounds accumulate | Accepted |
| [ADR-0019](0019-one-models-section.md) | One models section | Accepted |
| [ADR-0020](0020-halting-errors.md) | Halting outcomes raise RunInterrupted errors | Accepted |
| [ADR-0021](0021-resuming-approved-steps.md) | How approved steps resume | Accepted |
| [ADR-0022](0022-provider-extensions.md) | Provider extensions on messages and responses | Accepted |
| [ADR-0023](0023-validation-rule-when.md) | A validation rule's when describes a violation | Accepted |
| [ADR-0024](0024-loguru.md) | Logging through loguru | Accepted |
| [ADR-0025](0025-governor-placement.md) | Where the governor runs, and one way to combine policy rules | Accepted |
| [ADR-0026](0026-json-schema-subset.md) | A JSON Schema subset validator in the core | Accepted |
| [ADR-0027](0027-code-transport.md) | Code-executing tools use transport: code | Accepted |
| [ADR-0028](0028-manifests-for-code-tools.md) | Tools given in code carry manifests; stale pins block calls | Accepted |
| [ADR-0029](0029-routing-cascade.md) | Routing cascades and shared text scoring | Accepted |
| [ADR-0030](0030-context-governance.md) | Context governance runs before context.after | Accepted |
| [ADR-0031](0031-namespaced-memory.md) | A namespaced memory store, not a memory model | Accepted |
| [ADR-0032](0032-grounded-citations.md) | The grounded.citations guard | Accepted |
| [ADR-0033](0033-eval-datasets.md) | Eval datasets and graders | Accepted |
| [ADR-0034](0034-baselines-and-online-evals.md) | Eval baselines, exit codes and online sampling | Accepted |
| [ADR-0035](0035-record-and-replay.md) | Recording and replaying runs | Accepted |
| [ADR-0036](0036-dry-runs-and-guard-notes.md) | Governor dry runs and guard firing notes | Accepted |
| [ADR-0037](0037-framework-adapters.md) | One adapter object per agent framework | Accepted |
| [ADR-0038](0038-harnessd.md) | harnessd serves one spec over /v1 | Accepted |
| [ADR-0039](0039-gateways-and-dev-stack.md) | Gateway configs and the local dev stack | Accepted |
| [ADR-0040](0040-typescript-sdk.md) | The TypeScript SDK | Accepted |
| [ADR-0041](0041-docs-site.md) | The docs site: MkDocs and Material | Accepted |
| [ADR-0042](0042-docs-structure.md) | The docs follow FastAPI's structure, with tested tutorial code | Accepted |
| [ADR-0043](0043-profile-ownership.md) | Profiles an app's team can write merge after the platform's | Accepted |
