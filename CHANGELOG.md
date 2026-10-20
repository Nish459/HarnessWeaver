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
- L0/L1 modules (DESIGNS No. 16, No. 20, No. 22):
  - Guardrails: the spec's guards become middleware per stage (`input`, `context`, `tool_result`, `output`, `stream`) with action overrides, `log_only` shadow mode (R8), parallel groups, bands from the declaring layer, and the built-in guards `regex.deny`, `pii.regex`, `secrets.scan`, `injection.heuristic`, `size.limit`, `topic.deny` and `llm.judge`.
  - Validation: cel-lite business rules (`validation.rules`) as `output.before` middleware that asks for repairs (ADR-0023).
  - The offline `scripted` model provider (`ScriptedModel`): replies in order, rule matchers, streaming, failures.
  - Telemetry through the OpenTelemetry API: `harness.run`, `chat {model}`, `execute_tool {tool}`, `harness.guard`, `harness.decision` and `harness.approval` spans, GenAI token-usage and duration metrics and a `harness.cost` counter, names pinned to semantic conventions 1.42.0, and `capture_content` with post-redaction content only (R9).
- Wrap style: `harness.instrument(client)` finds an adapter from the client's type and governs its model calls, as their own small runs or inside a run or session (DESIGNS No. 15).
- `harnessweaver-openai`: the `openai.chat` provider (retries off, LiteLLM cost header, streaming) and the `instrument()` adapter for `OpenAI` / `AsyncOpenAI`.
- `harnessweaver-anthropic`: the `anthropic.messages` provider (adaptive thinking, `effort`, server-side refusal fallbacks on by default, thinking blocks replayed unchanged across a tool loop, streaming) and the `instrument()` adapter for `Anthropic` / `AsyncAnthropic`.
- `harnessweaver-otel`: the `otel.sdk` provider, which sets up the OpenTelemetry SDK with a console or OTLP exporter when `observability.configure_sdk: true` and leaves an app's own setup alone (R5).
- The test kit, `harnessweaver.testing`: `harness_for_test` (offline, fake clock, injected model, fake tools and deciders), `scripted` replies with `text` / `output` / `tool_call`, `FakeTool`, `FakeDecider`, `assert_trace` and `step`, `assert_no_content` (R9), and `Cassette` to record a real model's answers once and replay them offline.
- The conformance suite (T5): `pytest --harnessweaver-conformance=<namespace>` checks a plugin's metadata, that importing it is inert (S8), and that every contribution builds, returns valid results, is deterministic when it says so, blocks on timeout, leaks no raw content (R9), meets its latency class, and (for runners and adapters) fires only and all of its declared hooks (R4). Decorators take `sample=` for contributions that need settings. `make conformance` runs it on every first-party plugin and is part of `make check`.
- `Harness.from_spec(model=...)` replaces `models.provider` with a provider object, for tests and offline runs.
- `harnessweaver-cli`: the `harnessweaver` command with `init` (built-in and plugin templates), `spec validate`, `spec explain`, `spec diff` (either side can be `git:<ref>:<path>`), `doctor` (level and next steps, reachable hooks, duplicate retry owners, unpinned profiles, shadow guards, content capture), `hooks`, `test` (offline, test mode on) and `contracts export`, plus the `extraction` project template, whose output passes its own tests (T6).
- Example 01, `examples/01_invoice_extraction`: typed invoice extraction at L1 in the Run style, with PII redaction, a secrets check, business rules, a repaired answer, budgets and prices, and `l0_instrument.py`, which governs an existing OpenAI client in three lines. It runs offline and its tests run in CI, with no app-level retry or tracing code.
- `examples/_org/acme-baseline.yaml`: an org baseline profile (v1) with a locked plugin allow-list, locked guards and content capture, budget bounds and a required level per risk tier, with tests that each lock and bound fails loading.
- `Harness.runner_of(task)`: the runner a task uses and the hook points it reaches.
- Policy (DESIGNS No. 17, ADR-0025): the `PolicyEngine` port and the built-in `cel_lite` engine. Every engine combines `policy.rules` the same way (`hw.decide_by_rules`): deny beats require_approval beats allow, the first of equals decides, an unevaluable rule never loosens, and `default_effect` applies when none match. Rules take `hook: run.start` to restrict runs and sessions as they start. New contracts `PolicyRule`, `PolicyConfig`, `PolicyRequest` and `PolicyDecision`.
- Tool governance (DESIGNS No. 17): `kind: Tool` manifests (`tools.manifests`, `hw.ToolManifest`) with `native`, `http` and `code` transports, pinned definition digests (`hw.definition_digest`), rate limits, approval rules, output sanitizers and tenant allow-lists; and the nine-step governor every tool call passes, after the `tool.before` middleware and on its final arguments: registry and digest, a JSON Schema subset check (ADR-0026), policy, the lethal trifecta (`tools.trifecta`), rate limits held under concurrency, an optional `tools.judge` that can only tighten, approval (`tools.approval_by_risk`, tasks' `approvals.tools`), and sanitizing before `tool.after`. Each decision is a `harness.governor` trace note. Calls carry an idempotency key that survives resumption. Tools given in code carry manifests too (`ToolDescription.from_manifest`, ADR-0028).
- Approval channels (DESIGNS No. 18): the `ApprovalChannel` port and the built-in `memory`, `callback`, `console` and `webhook` channels, notified once a request is saved; a failing channel is traced and the run keeps waiting.
- The `Sandbox` port and `transport: code` tools (ADR-0027).
- `harnessweaver-cel`: the `cel.policy` engine, full CEL through cel-python, checked against the shared policy fixtures; its tests pin every `expr` fixture where full CEL and cel-lite differ.
- `harnessweaver-monty`: the `monty.sandbox` sandbox, running code tools in pydantic-monty workers with time and memory limits.
- Guard findings can be marked `private` (`pii.regex`'s are); finding private data marks the run private for the trifecta check (S3).
- Routing (DESIGNS No. 19, ADR-0029): `routing.<router>` cascades on `route.decide`, with the built-in `rules`, `lexical`, `semantic` (with the dependency-free `semantic.hashing` `Embedder`) and `llm` stages and any `@hw.decider`. The first confident stage wins, answers outside the options and failing stages abstain, the router's `default` answers otherwise, and every stage's answer is a `harness.routing` trace note. New `Embedder` port.
- Context (DESIGNS No. 21, ADR-0030): `context.<source>` with the built-in `memory` (documents with ACLs, searched lexically) and `passthrough` providers, and `s.context(name).fetch(query)`. Every item, fetched or passed to `check()`, has its ACL re-checked (`require_acl` drops items without one), is labelled with its source and trust, and is capped by `max_items` and `max_tokens` before the `context.after` middleware; every drop is traced. New `ContextProvider` port.
- Memory (ADR-0031): the `Memory` port, the in-process `memory` provider, the spec's `memory` section (`default_ttl`) and `s.memory` (`put`, `get`, `delete`, `entries`), namespaced per tenant, principal and task.
- The `grounded.citations` guard (ADR-0032): output sentences must cite, in square brackets, context ids the run kept; a run's kept ids survive suspension.
- Fixtures suite `routing`: tokens, similarity, the hashing embedder, the `rules` and `lexical` stages and the cascade. The conformance suite checks context providers (valid items, only what the tenant may see), embedders and memory stores.
- Evals (DESIGNS No. 23, ADR-0033, ADR-0034): one dataset format (`suite`, `task`, `graders`, `thresholds`, `cases` with `input`, `expect` and their own `graders`), graders as `Evaluator` providers (the new port), the deterministic graders `exact`, `field_equals`, `numeric_close`, `contains`, `regex`, `citation_present`, `schema_valid`, `guard_fired` and `status`, and the `llm_judge` grader, which grades in a governed session. `Harness.evaluate(dataset)` runs a suite and returns a `SuiteResult`; `Harness.output_schema(task)` gives a task's output schema.
- Online evals: `evals.online.sample_rate` samples runs by their id at `run.end`, grades them with `evals.online.graders` (deterministic only) and keeps an `OnlineSample` per run; `Harness.samples()` reads them. Sampling fails open.
- The shadow-guard report: how often each `log_only` guard would fire, with false positives and misses against what eval cases expect (R8).
- `harnessweaver eval run` (baselines in `.harness/baselines/<task>.<suite>.json`, `--update-baseline`, the shadow-guard report; exit 1 on a missed threshold or a regression, 2 when the suites can't run) and `harnessweaver eval report` (online samples).
- `Harness.authorize(tool, args, ...)`: the governor's verdict on a call as a dry run, using up no rate limit (ADR-0036); `harnessweaver policy test` checks a table of calls against it (`policy_tests.yaml`; exit 1 on a mismatch, 2 when the tests can't run).
- Recording and replay (ADR-0035): with `state.record: true` a run keeps its model answers, tool results and approvals; `Harness.replay(run_id)` and `harnessweaver replay <run_id>` run it again against the current code and spec without calling out or running tools, and report changed statuses, outputs and decisions (exit 1 when the status or output changed).
- Fixtures suite `evals`: graders, dataset labels, summaries and baselines, sampling and the shadow-guard report. Schemas `eval-dataset`, `eval-sample`, `grade`, `suite-result`, `baseline`, `online-sample`, `policy-tests`, `recorded-call` and `replay-report`. The conformance suite checks evaluators (valid grades with no raw content, repeatable when deterministic, within their latency class) and state-store recordings and samples.
- Guards that fire, or would fire in shadow mode, are traced as `harness.guard` notes (codes `guard_fired` and `guard_shadow`) naming the guard in full, like `guardrails.input[pii]`.
- `harnessweaver doctor` warns about tool manifests without a pinned digest (printing the digest to pin) and fails ones that changed since they were pinned.
- The conformance suite checks policy engines (valid, repeatable decisions within their latency class), sandboxes (code runs; it can't read a host file) and approval channels; `make conformance` now covers `cel` and `monty` too.
- Fixtures suite `governor`: canonical JSON and digests, rate syntax, the JSON Schema subset, policy combination, governor steps 1 to 7 and step 9. Schemas `tool-manifest`, `tool-verdict`, `policy-request`, `policy-decision` and `sandbox-result`.
- Each repair attempt is traced as a note with code `repair`, giving field locations and messages but never the values (R13, R9).
- `Message.extensions` and `ModelResponse.extensions` for provider data replayed unchanged with a turn (ADR-0022).
- `HARNESSWEAVER_TEST_MODE=1` (`harnessweaver.ports.network_allowed`) makes live providers refuse to call out; every test runs with it (R14).
- A spec that uses a section whose module this release doesn't have yet (the sidecar) fails to load instead of running without that control (R4).
- Errors `NotFound` and `RunInterrupted` (`RunBlocked`, `RunEscalated`, `RunSuspended`) with codes `not_found`, `blocked`, `escalated` and `suspended` (ADR-0020).
- JSON Schemas for every contract under `contracts/schemas`, with `make schemas` / `make schemas-check` and a drift test (ADR-0005).
- Language-neutral conformance fixtures under `contracts/fixtures/conformance` (suites `durations`, `semver`, `outcomes`, `hook_order`, `expr`, `merge`, `levels`, `bus`, `budgets`, `plugins`, `guards`) and their Python runners.
- Hypothesis property tests for outcome combination, cel-lite arithmetic and logic, durations and versions (T3).
- uv workspace with the core package `harnessweaver`, the developer tooling `harnessweaver-cli` (the `harnessweaver` command), the sidecar `harnessweaver-sidecar` (`harnessd`; `GET /v1/health` so far), and package skeletons for the first-party plugins `harnessweaver-openai`, `harnessweaver-anthropic`, `harnessweaver-pydantic-ai`, `harnessweaver-monty`, `harnessweaver-otel` and `harnessweaver-cel`.
- Core extras that pull in first-party plugins: `harnessweaver[openai]`, `[anthropic]`, `[pydantic-ai]`, `[monty]`, `[otel]`, `[cel]`, `[cli]`, `[sidecar]` and `[all]`.
- A test that keeps the core's runtime dependencies to `pydantic`, `opentelemetry-api`, `pyyaml`, `anyio` and `loguru` (RULES R6).
- `make check` (ruff, ruff format, pyright, pytest), CI on Python 3.12-3.14 with SHA-pinned actions, pre-commit hooks and a pull request template.
- `make check` also rejects characters that aren't on a standard keyboard (`scripts/check_ascii.py`, RULES D5).

### Changed

- The `StateStore` port gains `append_recording`, `recording`, `put_sample` and `samples`, and the `ToolGovernor` port's `authorize` takes `dry_run`. `Harness.from_spec` takes a `state` store; given `telemetry`, it no longer configures an OpenTelemetry SDK itself.
- The extraction template's and Example 01's offline overlays answer every golden case, so `harnessweaver eval run -e offline` passes on them; both test their golden sets.
- Logging goes through loguru (ADR-0024), which becomes the core's fifth dependency (RULES R6). The core and `harnessweaver-otel` are silent until the app opts in with `logger.enable("harnessweaver")` / `logger.enable("harnessweaver_otel")`, and never add sinks. The conformance suite's raw-content check (R9) captures loguru and `logging` output alike.
- Large modules are now packages of focused modules, each package's `__init__` exporting what other code imports: `harnessweaver.harness` (the `Harness` class is built from mixins for runs, endings, approvals and sessions), `core.context`, `core.plugins`, `core.registry`, `core.telemetry`, `spec.loader`, `spec.merge`, `spec.models`, `modules.guardrails.pipeline`, `modules.guardrails.providers` (one module per built-in guard) and `testing.conformance`; `core.expr` gains `grammar`, `declared` and `operations` modules. The public API (`import harnessweaver as hw`) is unchanged.
