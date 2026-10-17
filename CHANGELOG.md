# Changelog

All notable changes to the HarnessWeaver packages are recorded here. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and every package uses [Semantic Versioning](https://semver.org/) independently (RULES V1).

## [Unreleased]

### Added

- Contracts and core primitives in `harnessweaver` (public API in `harnessweaver/__init__.py`):
  - `Envelope`, `Principal`, `Labels`, `Budget`, and the injectable `Clock` (`SystemClock`, `FakeClock`).
  - The 13 `HookPoint`s with their direction, the middleware `Band`s, `execution_order`, and a typed event payload per hook point (`HookEvent`).
  - The outcomes `Continue`, `Retry`, `Escalate`, `Suspend` and `Block`, with severity and `most_severe`.
  - `Decision` / `DecisionRequest` for routing, `PolicyEffect` and `tighten` (R3), `GuardResult` and its seven `GuardAction`s.
  - Neutral model and tool contracts: `Message`, `ToolCall`, `ToolSpec`, `ModelRequest`, `ModelResponse`, `Usage`, `StreamChunk`, `ToolInfo`, `ToolResult`, `ContextItem`, `Acl`, `ApprovalRequest`, `ApprovalDecision`, `RunStatus`.
  - The error taxonomy in `harnessweaver.errors`, with stable codes and `ErrorInfo`.
  - The `Duration` type (`"250ms"`, `"20s"`, `"1h30m"`) and SemVer versions and npm-style ranges.
  - cel-lite, the built-in CEL-subset expression language (ADR-0004).
- The spec system in `harnessweaver.spec` (`load_spec`, `EffectiveSpec`, `HarnessSpec`, `ProfileSpec`, `Level`):
  - YAML 1.2 (core schema) loading with duplicate-key errors (ADR-0017).
  - Layering of the built-in `defaults` profile, built-in profiles (`profile://rag`), org profiles (`org://acme-baseline@^2`, highest matching version from `HARNESSWEAVER_PROFILE_PATH` or `.harness/profiles`), file profiles, the app spec and an environment overlay (`harness.<env>.yaml`, selected by `HARNESSWEAVER_ENV`).
  - Keyed-list merging by `id` with generated ids, locks (R1, ADR-0018), bounds that never clamp (R10), and provenance for every value.
  - Per-run budget overrides that may only lower overridable fields (`EffectiveSpec.run_budget`).
  - Adoption levels L0-L4 with requirement codes, enforced against the org's `require_level` (`LevelTooLow`).
  - cel-lite policy and validation rules compiled at load against their allowed names.
  - `spec explain` and `spec diff` building blocks (`render_explain`, `diff_specs`, `render_diff`).
  - Built-in profiles: `defaults`, `extraction`, `rag`, `agent`, `workflow`, `chat`.
- The runtime (DESIGNS No. 7, No. 8, No. 15, No. 18):
  - `Harness` (`hw.load` / `Harness.load`, `from_spec`), with `run`, `submit`, `stream`, `result`, `approve`, `resume`, `cancel`, `session`, `explain` and `hooks`. Loading resolves every name through the plugin registry, installs the spec's `middleware:`, builds each task's runner and fails if a runner can't reach a hook the baseline or the budgets need (R4).
  - The hook bus: bands, onion order, payload chaining, `Block` short-circuits, fail modes and timeouts, baseline middleware must fail closed (R2), and every outcome traced (R13) in a `RunTrace`.
  - `RunContext` with governed operations for every integration style: model calls (alias resolution, `allowed_aliases`, streaming with `stream.chunk`), tool calls, routing, context, input and output checks, budgets (ADR-0012), deadlines and data labels (S3).
  - Built-in runners `direct` (bounded tool loop, typed output with bounded repair), `session` and `workflow` (step DAG, parallel steps, evaluator-optimizer loops), and standalone `Session`s.
  - Approvals: `Suspend` at `tool.before` and `output.before`, checkpoints, approve / edit / reject, expiry, grants matched by call or output, resume after a crash, and cancellation (ADR-0021). Idempotency keys.
  - State stores `memory` and `sqlite` (ADR-0009), versioned prompts by `name@version` (ADR-0013), and the port Protocols in `harnessweaver.ports`.
- The plugin contract (DESIGNS No. 13, ADR-0015): `Plugin`, the `@provider`, `@middleware`, `@decider`, `@runner` and `@adapter` decorators, `RESERVED_NAMESPACES` and `CONTRACT_VERSION`. Discovery reads entry-point metadata without importing anything (S8); plugins load only when the spec references their namespace, from the `harnessweaver.plugins` entry points or `plugins.local`; `plugins.allow`, namespace conflicts and contract ranges (V5) are checked at load; plugins can ship profiles (`profile://acme.baseline@^1`). The core's own runners and state stores are its built-in plugin.
- A spec that uses a section whose module this release doesn't have yet (guardrails, validation rules, policy, routing, context, tool manifests, telemetry exporters, online evals, the sidecar) fails to load instead of running without that control (R4).
- Errors `NotFound` and `RunInterrupted` (`RunBlocked`, `RunEscalated`, `RunSuspended`) with codes `not_found`, `blocked`, `escalated` and `suspended` (ADR-0020).
- JSON Schemas for every contract under `contracts/schemas`, with `make schemas` / `make schemas-check` and a drift test (ADR-0005).
- Language-neutral conformance fixtures under `contracts/fixtures/conformance` (suites `durations`, `semver`, `outcomes`, `hook_order`, `expr`, `merge`, `levels`, `bus`, `budgets`, `plugins`) and their Python runners.
- Hypothesis property tests for outcome combination, cel-lite arithmetic and logic, durations and versions (T3).
- uv workspace with the core package `harnessweaver`, the developer tooling `harnessweaver-cli` (the `harnessweaver` command; `--version` so far), the sidecar `harnessweaver-sidecar` (`harnessd`; `GET /v1/health` so far), and package skeletons for the first-party plugins `harnessweaver-openai`, `harnessweaver-anthropic`, `harnessweaver-pydantic-ai`, `harnessweaver-monty`, `harnessweaver-otel` and `harnessweaver-cel`.
- Core extras that pull in first-party plugins: `harnessweaver[openai]`, `[anthropic]`, `[pydantic-ai]`, `[monty]`, `[otel]`, `[cel]`, `[cli]`, `[sidecar]` and `[all]`.
- A test that keeps the core's runtime dependencies to `pydantic`, `opentelemetry-api`, `pyyaml` and `anyio` (RULES R6).
- `make check` (ruff, ruff format, pyright, pytest), CI on Python 3.12-3.14 with SHA-pinned actions, pre-commit hooks and a pull request template.
- `make check` also rejects characters that aren't on a standard keyboard (`scripts/check_ascii.py`, RULES D5).
