# Changelog: harnessweaver

All notable changes to the core package. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this package uses [Semantic Versioning](https://semver.org/) on its own (RULES V1). Versions before 0.18.0 were never published; their Git tags (`harnessweaver@<version>`) mark the commit where each one landed.

## [Unreleased]

### Added

- `email` approval channel: sends each approval request by e-mail via SMTP, using only the standard library. Credentials come from environment variables (S1). Refuses the network in test mode (R14). A failed send is traced as `approval_notify_failed`, like any channel.

## 0.18.0 - 2026-11-02

The first version published to PyPI.

### Added

- `harnessweaver.errors.ModelRefusal`, a `RunBlocked` with code `model_refusal` that a model provider raises when the model declines. Its `response` carries what the call used.

### Fixed

- A governed model call counts the usage and cost of a request the model declined, and notes the refusal on the trace (RULES R13), before it ends the run. It doesn't run `model.after`.

## 0.17.1 - 2026-11-01

### Added

- The package ships the Apache-2.0 `LICENSE` in its wheel and sdist.

### Fixed

- The package's README no longer says it isn't published.

## 0.17.0 - 2026-11-01

### Security

- Approvals bind what they should (ADR-0044, ADR-0045):
  - One tool-call approval no longer authorizes every later identical call in the run. A grant covers one execution, and a repeat asks again. `approvals.grant_scope: run` keeps the old run-wide behavior. **This changes behavior for existing specs.**
  - An approval given for another step's ask no longer satisfies a role the approver doesn't hold. Governor step 7 checks the manifest's `approver_role`, else the task's, else the spec's. When they differ the run asks again, keeping any edit, so that takes two approvals unless one person holds both roles.
  - Concurrent answers to one approval can no longer each resume the run. `approve()` claims the request through the new `StateStore.claim_approval`, including across processes on one SQLite file. The loser gets `NotFound` (HTTP 404 from harnessd) and records nothing. `cancel()` claims too. **A third-party `StateStore` must add this method.**

### Fixed

- A `workflow` run that suspended again before another step finished lost its finished steps from the checkpoint, so they ran again.

## 0.16.0 - 2026-11-01

### Security

Model and tool content could get past a runtime control. Each of these now holds (S2, R1, R4, R11):

- A value a `session` or `workflow` handler, or a custom runner, returned skipped `output.before`, so output guards and validation rules didn't apply to it, not even a locked baseline guard. The harness now fires `output.before` on every task's final output, unless the run just accepted exactly that value (`s.generate`, `s.validate`, the `direct` runner). **Changed:** a handler that returns unchecked content a guard objects to now ends blocked, or follows `validation.on_failure` for a repair, since nothing is left to repair it. Runner conformance no longer counts `output.before` as a hook the runner fires itself.
- The `direct` runner ran any registered tool the model named, skipping the approvals of the task that does offer it. A registered tool the task's `tools` don't list now blocks the run with code `tool_not_offered`, before `tool.before`.
- Guards never saw JSON object keys, and `pii_redact` and `strip_instructions` skipped them, so an object keyed by e-mail address reached the model and a secret in a key passed `secrets.scan`. Keys are now checked and redacted like values. Keys that redact to one name stay distinct (`[EMAIL]`, `[EMAIL]#2`), so no entry is lost. **Changed:** a guard also sees field names, so one that flags a field name of a typed output sends it to repair.

## 0.15.0 - 2026-11-01

### Security

An app's team could shed org baseline controls with files in its own repository. These all fail loading now (R1, R2, R10, ADR-0043):

- Wildcard locks (`guardrails.input[*]`, `tasks.*.budget`) were never enforced. They now cover every key or item, including ones added later, and `spec explain` shows them.
- A profile in the app's `.harness/profiles` with a higher version replaced the platform's baseline of the same name. The first directory on the search path holding a name now owns it, and versions are never compared across directories. **Changed:** a platform that splits versions of one name across directories must keep them together.
- A profile the app listed before its baseline could put keys into items the baseline then locked. Profiles the app's team can write now merge after the platform's.
- An app file with the same reference text as a platform profile's parent displaced that parent. Profiles are now told apart by file, for duplicates and cycles, so the same relative text in two directories is no longer called a cycle.
- `null` at a path with a `max` bound removed the limit and passed the bound. It's now a `BoundViolation`.
- A baseline guard that fails open passed the R2 check when it sat in a parallel group with a closed one. Each guard is now checked. **Changed:** such a baseline now fails loading.
- An item with the merger's temporary id (`~autoN~`) could edit a locked item that had no id. Those ids are now reserved.
- A locked `where: sidecar` guard followed an unlocked `sidecar.url`, so a later layer could repoint it. **Changed:** a baseline that locks such a guard must now lock `sidecar.url` too.
- A `__proto__` key in a spec layer now fails loading.

## 0.14.0 - 2026-10-26

### Removed

- `@hw.provider` no longer accepts the planned ports `DatasetStore`, `ErrorClassifier`, `ToolRegistry` and `Validator`: nothing calls providers for them yet, so declaring one is now an `unknown port` error instead of a provider that never runs. DESIGNS.md No. 14 marks them planned.
- `@hw.provider` no longer accepts `port="ToolGovernor"`. The harness always builds its own governor, which enforces the baseline, so a spec can't select another one (R1) and such a provider never ran. The `ToolGovernor` Protocol stays in `harnessweaver.ports`.
- `NoSettings` (from `harnessweaver.modules.evals.graders`): the `exact` and `schema_valid` graders declare no config, as other settings-free providers do, and reject settings with `takes no settings`.

## 0.13.1 - 2026-10-25

### Fixed

- `Harness.authorize` (and so `harnessweaver policy test` and harnessd's `POST /v1/tools/{name}/authorize`) gave an approval verdict only the manifest's `approval.approver_role`, while a real run falls back to the task's and then the spec's `approvals.approver_role`. A dry run now names the role a real run waits for (DESIGNS No. 18).

## 0.13.0 - 2026-10-20

### Added

- Tool manifests take `server`, the MCP server of a `transport: mcp` tool.
- The `tool-allow-list` contract (`ToolAllowList`, in `harnessweaver.core.gateway`) that `harnessweaver gateway mcp` writes (ADR-0039).

## 0.12.0 - 2026-10-20

### Added

- Guards declared `where: sidecar` run their provider in harnessd at `sidecar.url`, with the token from `sidecar.token_env`; the guard's fail mode applies when the sidecar can't answer (R2), and `plugins.allow` still applies to the provider's name (S8).
- `Harness.decide_policy` (the policy engine's answer alone), `Harness.output_type`, and `Session.validate(..., output=type)`, which parses a value into a type before `output.before`.
- The sidecar's request models, as contracts in `harnessweaver.core.sidecar` (ADR-0038).

## 0.11.2 - 2026-10-20

### Fixed

- `Harness.runner_of()`, and so `harnessweaver doctor`, failed for a task run by a plugin's runner (such as `pydantic_ai.agent`): it looked the runner up by its short name.

## 0.11.1 - 2026-10-20

### Fixed

- Brings the fix from 0.10.1 into the line that has 0.11.0, which was built alongside it.

## 0.11.0 - 2026-10-20

### Added

- `Harness.wrap(agent, task=...)`: wrap style for agent frameworks, with the adapter found from the agent's type as `instrument()` finds one (DESIGNS No. 15, ADR-0037).
- Adapters govern what their framework runs itself: `RunContext.call_tool(call, backend=...)` runs a framework's own tool through `tool.before`, the governor and `tool.after`, and `RunContext.approval_needed(call, reason)` brings an approval the framework asks for to the harness's approvers. During a replay the recording answers an adapter's own model and tool calls too (`RunContext.replaying`, ADR-0035).

## 0.10.1 - 2026-10-20

### Fixed

- A guard with `action: require_approval` in `guardrails.output` asked for approval again after a human approved the output, so the run never completed. The guardrails pipeline now honours `OutputEvent.approval`: the approval answers `require_approval` and is traced as a `guard_approved` note, while `block`, `escalate`, `repair`, redactions and shadow guards still apply (DESIGNS No. 18, No. 20). The `guards` conformance fixtures gain approved-output cases (`approved: true`).

## 0.10.0 - 2026-10-20

### Added

- Evals (DESIGNS No. 23, ADR-0033, ADR-0034): one dataset format (`suite`, `task`, `graders`, `thresholds`, `cases` with `input`, `expect` and their own `graders`), graders as `Evaluator` providers (the new port), the deterministic graders `exact`, `field_equals`, `numeric_close`, `contains`, `regex`, `citation_present`, `schema_valid`, `guard_fired` and `status`, and the `llm_judge` grader, which grades in a governed session. `Harness.evaluate(dataset)` runs a suite and returns a `SuiteResult`; `Harness.output_schema(task)` gives a task's output schema.
- Online evals: `evals.online.sample_rate` samples runs by their id at `run.end`, grades them with `evals.online.graders` (deterministic only) and keeps an `OnlineSample` per run; `Harness.samples()` reads them. Sampling fails open.
- The shadow-guard report: how often each `log_only` guard would fire, with false positives and misses against what eval cases expect (R8).
- `Harness.authorize(tool, args, ...)`: the governor's verdict on a call as a dry run, using up no rate limit (ADR-0036).
- Recording and replay (ADR-0035): with `state.record: true` a run keeps its model answers, tool results and approvals; `Harness.replay(run_id)` runs it again against the current code and spec without calling out or running tools, and reports changed statuses, outputs and decisions.
- Fixtures suite `evals`: graders, dataset labels, summaries and baselines, sampling and the shadow-guard report. Schemas `eval-dataset`, `eval-sample`, `grade`, `suite-result`, `baseline`, `online-sample`, `policy-tests`, `recorded-call` and `replay-report`. The conformance suite checks evaluators (valid grades with no raw content, repeatable when deterministic, within their latency class) and state-store recordings and samples.
- Guards that fire, or would fire in shadow mode, are traced as `harness.guard` notes (codes `guard_fired` and `guard_shadow`) naming the guard in full, like `guardrails.input[pii]`.

### Changed

- The `StateStore` port gains `append_recording`, `recording`, `put_sample` and `samples`, and the `ToolGovernor` port's `authorize` takes `dry_run`. `Harness.from_spec` takes a `state` store; given `telemetry`, it no longer configures an OpenTelemetry SDK itself.

## 0.9.0 - 2026-10-20

### Added

- Routing (DESIGNS No. 19, ADR-0029): `routing.<router>` cascades on `route.decide`, with the built-in `rules`, `lexical`, `semantic` (with the dependency-free `semantic.hashing` `Embedder`) and `llm` stages and any `@hw.decider`. The first confident stage wins, answers outside the options and failing stages abstain, the router's `default` answers otherwise, and every stage's answer is a `harness.routing` trace note. New `Embedder` port.
- Context (DESIGNS No. 21, ADR-0030): `context.<source>` with the built-in `memory` (documents with ACLs, searched lexically) and `passthrough` providers, and `s.context(name).fetch(query)`. Every item, fetched or passed to `check()`, has its ACL re-checked (`require_acl` drops items without one), is labelled with its source and trust, and is capped by `max_items` and `max_tokens` before the `context.after` middleware; every drop is traced. New `ContextProvider` port.
- Memory (ADR-0031): the `Memory` port, the in-process `memory` provider, the spec's `memory` section (`default_ttl`) and `s.memory` (`put`, `get`, `delete`, `entries`), namespaced per tenant, principal and task.
- The `grounded.citations` guard (ADR-0032): output sentences must cite, in square brackets, context ids the run kept; a run's kept ids survive suspension.
- Fixtures suite `routing`: tokens, similarity, the hashing embedder, the `rules` and `lexical` stages and the cascade. The conformance suite checks context providers (valid items, only what the tenant may see), embedders and memory stores.

## 0.8.0 - 2026-10-19

### Added

- Policy (DESIGNS No. 17, ADR-0025): the `PolicyEngine` port and the built-in `cel_lite` engine. Every engine combines `policy.rules` the same way (`hw.decide_by_rules`): deny beats require_approval beats allow, the first of equals decides, an unevaluable rule never loosens, and `default_effect` applies when none match. Rules take `hook: run.start` to restrict runs and sessions as they start. New contracts `PolicyRule`, `PolicyConfig`, `PolicyRequest` and `PolicyDecision`.
- Tool governance (DESIGNS No. 17): `kind: Tool` manifests (`tools.manifests`, `hw.ToolManifest`) with `native`, `http` and `code` transports, pinned definition digests (`hw.definition_digest`), rate limits, approval rules, output sanitizers and tenant allow-lists; and the nine-step governor every tool call passes, after the `tool.before` middleware and on its final arguments: registry and digest, a JSON Schema subset check (ADR-0026), policy, the lethal trifecta (`tools.trifecta`), rate limits held under concurrency, an optional `tools.judge` that can only tighten, approval (`tools.approval_by_risk`, tasks' `approvals.tools`), and sanitizing before `tool.after`. Each decision is a `harness.governor` trace note. Calls carry an idempotency key that survives resumption. Tools given in code carry manifests too (`ToolDescription.from_manifest`, ADR-0028).
- Approval channels (DESIGNS No. 18): the `ApprovalChannel` port and the built-in `memory`, `callback`, `console` and `webhook` channels, notified once a request is saved; a failing channel is traced and the run keeps waiting.
- The `Sandbox` port and `transport: code` tools (ADR-0027).
- Guard findings can be marked `private` (`pii.regex`'s are); finding private data marks the run private for the trifecta check (S3).
- The conformance suite checks policy engines (valid, repeatable decisions within their latency class), sandboxes (code runs; it can't read a host file) and approval channels.
- Fixtures suite `governor`: canonical JSON and digests, rate syntax, the JSON Schema subset, policy combination, governor steps 1 to 7 and step 9. Schemas `tool-manifest`, `tool-verdict`, `policy-request`, `policy-decision` and `sandbox-result`.

## 0.7.0 - 2026-10-19

### Changed

- Logging goes through loguru (ADR-0024), which becomes the core's fifth dependency (RULES R6). The core is silent until the app opts in with `logger.enable("harnessweaver")`, and never adds sinks. The conformance suite's raw-content check (R9) captures loguru and `logging` output alike.
- Large modules are now packages of focused modules, each package's `__init__` exporting what other code imports: `harnessweaver.harness` (the `Harness` class is built from mixins for runs, endings, approvals and sessions), `core.context`, `core.plugins`, `core.registry`, `core.telemetry`, `spec.loader`, `spec.merge`, `spec.models`, `modules.guardrails.pipeline`, `modules.guardrails.providers` (one module per built-in guard) and `testing.conformance`; `core.expr` gains `grammar`, `declared` and `operations` modules. The public API (`import harnessweaver as hw`) is unchanged.

## 0.6.0 - 2026-10-18

### Added

- `Harness.runner_of(task)`: the runner a task uses and the hook points it reaches.
- Each repair attempt is traced as a note with code `repair`, giving field locations and messages but never the values (R13, R9).

## 0.5.0 - 2026-10-18

### Added

- The test kit, `harnessweaver.testing`: `harness_for_test` (offline, fake clock, injected model, fake tools and deciders), `scripted` replies with `text` / `output` / `tool_call`, `FakeTool`, `FakeDecider`, `assert_trace` and `step`, `assert_no_content` (R9), and `Cassette` to record a real model's answers once and replay them offline.
- The conformance suite (T5): `pytest --harnessweaver-conformance=<namespace>` checks a plugin's metadata, that importing it is inert (S8), and that every contribution builds, returns valid results, is deterministic when it says so, blocks on timeout, leaks no raw content (R9), meets its latency class, and (for runners and adapters) fires only and all of its declared hooks (R4). Decorators take `sample=` for contributions that need settings.
- `Harness.from_spec(model=...)` replaces `models.provider` with a provider object, for tests and offline runs.

## 0.4.0 - 2026-10-18

### Added

- L0/L1 modules (DESIGNS No. 16, No. 20, No. 22):
  - Guardrails: the spec's guards become middleware per stage (`input`, `context`, `tool_result`, `output`, `stream`) with action overrides, `log_only` shadow mode (R8), parallel groups, bands from the declaring layer, and the built-in guards `regex.deny`, `pii.regex`, `secrets.scan`, `injection.heuristic`, `size.limit`, `topic.deny` and `llm.judge`.
  - Validation: cel-lite business rules (`validation.rules`) as `output.before` middleware that asks for repairs (ADR-0023).
  - The offline `scripted` model provider (`ScriptedModel`): replies in order, rule matchers, streaming, failures.
  - Telemetry through the OpenTelemetry API: `harness.run`, `chat {model}`, `execute_tool {tool}`, `harness.guard`, `harness.decision` and `harness.approval` spans, GenAI token-usage and duration metrics and a `harness.cost` counter, names pinned to semantic conventions 1.42.0, and `capture_content` with post-redaction content only (R9).
- Wrap style: `harness.instrument(client)` finds an adapter from the client's type and governs its model calls, as their own small runs or inside a run or session (DESIGNS No. 15).
- `Message.extensions` and `ModelResponse.extensions` for provider data replayed unchanged with a turn (ADR-0022).
- `HARNESSWEAVER_TEST_MODE=1` (`harnessweaver.ports.network_allowed`) makes live providers refuse to call out; every test runs with it (R14).
- Conformance fixtures suite `guards`.

## 0.3.0 - 2026-10-17

### Added

- The runtime (DESIGNS No. 7, No. 8, No. 15, No. 18):
  - `Harness` (`hw.load` / `Harness.load`, `from_spec`), with `run`, `submit`, `stream`, `result`, `approve`, `resume`, `cancel`, `session`, `explain` and `hooks`. Loading resolves every name through the plugin registry, installs the spec's `middleware:`, builds each task's runner and fails if a runner can't reach a hook the baseline or the budgets need (R4).
  - The hook bus: bands, onion order, payload chaining, `Block` short-circuits, fail modes and timeouts, baseline middleware must fail closed (R2), and every outcome traced (R13) in a `RunTrace`.
  - `RunContext` with governed operations for every integration style: model calls (alias resolution, `allowed_aliases`, streaming with `stream.chunk`), tool calls, routing, context, input and output checks, budgets (ADR-0012), deadlines and data labels (S3).
  - Built-in runners `direct` (bounded tool loop, typed output with bounded repair), `session` and `workflow` (step DAG, parallel steps, evaluator-optimizer loops), and standalone `Session`s.
  - Approvals: `Suspend` at `tool.before` and `output.before`, checkpoints, approve / edit / reject, expiry, grants matched by call or output, resume after a crash, and cancellation (ADR-0021). Idempotency keys.
  - State stores `memory` and `sqlite` (ADR-0009), versioned prompts by `name@version` (ADR-0013), and the port Protocols in `harnessweaver.ports`.
- The plugin contract (DESIGNS No. 13, ADR-0015): `Plugin`, the `@provider`, `@middleware`, `@decider`, `@runner` and `@adapter` decorators, `RESERVED_NAMESPACES` and `CONTRACT_VERSION`. Discovery reads entry-point metadata without importing anything (S8); plugins load only when the spec references their namespace, from the `harnessweaver.plugins` entry points or `plugins.local`; `plugins.allow`, namespace conflicts and contract ranges (V5) are checked at load; plugins can ship profiles (`profile://acme.baseline@^1`). The core's own runners and state stores are its built-in plugin.
- A spec that uses a section whose module isn't built yet fails to load instead of running without that control (R4). Later versions add those modules, and 0.12.0 the last of them.
- Errors `NotFound` and `RunInterrupted` (`RunBlocked`, `RunEscalated`, `RunSuspended`) with codes `not_found`, `blocked`, `escalated` and `suspended` (ADR-0020).
- Conformance fixtures suites `bus`, `budgets` and `plugins`.

## 0.2.0 - 2026-10-17

### Added

- The spec system in `harnessweaver.spec` (`load_spec`, `EffectiveSpec`, `HarnessSpec`, `ProfileSpec`, `Level`):
  - YAML 1.2 (core schema) loading with duplicate-key errors (ADR-0017).
  - Layering of the built-in `defaults` profile, built-in profiles (`profile://rag`), org profiles (`org://acme-baseline@^2`, highest matching version from `HARNESSWEAVER_PROFILE_PATH` or `.harness/profiles`), file profiles, the app spec and an environment overlay (`harness.<env>.yaml`, selected by `HARNESSWEAVER_ENV`).
  - Keyed-list merging by `id` with generated ids, locks (R1, ADR-0018), bounds that never clamp (R10), and provenance for every value.
  - Per-run budget overrides that may only lower overridable fields (`EffectiveSpec.run_budget`).
  - Adoption levels L0-L4 with requirement codes, enforced against the org's `require_level` (`LevelTooLow`).
  - cel-lite policy and validation rules compiled at load against their allowed names.
  - `spec explain` and `spec diff` building blocks (`render_explain`, `diff_specs`, `render_diff`).
  - Built-in profiles: `defaults`, `extraction`, `rag`, `agent`, `workflow`, `chat`.
- Conformance fixtures suites `merge` and `levels`.

## 0.1.0 - 2026-10-17

### Added

- Contracts and core primitives (public API in `harnessweaver/__init__.py`):
  - `Envelope`, `Principal`, `Labels`, `Budget`, and the injectable `Clock` (`SystemClock`, `FakeClock`).
  - The 13 `HookPoint`s with their direction, the middleware `Band`s, `execution_order`, and a typed event payload per hook point (`HookEvent`).
  - The outcomes `Continue`, `Retry`, `Escalate`, `Suspend` and `Block`, with severity and `most_severe`.
  - `Decision` / `DecisionRequest` for routing, `PolicyEffect` and `tighten` (R3), `GuardResult` and its seven `GuardAction`s.
  - Neutral model and tool contracts: `Message`, `ToolCall`, `ToolSpec`, `ModelRequest`, `ModelResponse`, `Usage`, `StreamChunk`, `ToolInfo`, `ToolResult`, `ContextItem`, `Acl`, `ApprovalRequest`, `ApprovalDecision`, `RunStatus`.
  - The error taxonomy in `harnessweaver.errors`, with stable codes and `ErrorInfo`.
  - The `Duration` type (`"250ms"`, `"20s"`, `"1h30m"`) and SemVer versions and npm-style ranges.
  - cel-lite, the built-in CEL-subset expression language (ADR-0004).
- JSON Schemas for every contract under `contracts/schemas`, with `make schemas` / `make schemas-check` and a drift test (ADR-0005).
- Language-neutral conformance fixtures under `contracts/fixtures/conformance` (suites `durations`, `semver`, `outcomes`, `hook_order` and `expr`) and their Python runners.
- Hypothesis property tests for outcome combination, cel-lite arithmetic and logic, durations and versions (T3).
- Extras that pull in first-party plugins: `harnessweaver[openai]`, `[anthropic]`, `[pydantic-ai]`, `[monty]`, `[otel]`, `[cel]`, `[cli]`, `[sidecar]` and `[all]`.
- A test that keeps the core's runtime dependencies to a fixed list (RULES R6).
