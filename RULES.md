# HarnessWeaver Engineering Rules

These are the non-negotiable rules for building HarnessWeaver. They are numbered so reviews, commits and code comments can cite them ("this violates **R3**").

- The **invariants (R)** protect the framework's promises to the teams that adopt it. They override every other rule and every feature request.
- The **coding (C), testing (T), security (S), docs (D), versioning (V) and git (G) rules** keep the codebase consistent.
- If a rule blocks something that is genuinely needed, write an ADR proposing the change: a file in [`docs/adr/`](docs/adr/index.md), indexed in [DESIGNS.md No. 28](DESIGNS.md#28-architecture-decision-records). Don't work around the rule in code.

When two design goals conflict, the earlier goal in [DESIGNS.md, Design goals](DESIGNS.md#3-design-goals-and-non-goals) wins.

---

## Architecture invariants

| ID | Rule | How it is enforced |
| --- | --- | --- |
| **R1** | **Baseline controls cannot be removed.** A locked path or a baseline list item can't be overridden, removed or reordered by any later layer. Any attempt is a load error. | `spec/merge/` lock checks; `merge` conformance fixtures; property tests |
| **R2** | **The baseline fails closed.** Every middleware declares `fail_mode`. Baseline-band middleware must be `closed`; declaring `open` there is a load error. | `@middleware` requires `fail_mode`; the bus coerces nothing; loader check |
| **R3** | **Probabilistic components never grant.** Classifiers, LLM judges, semantic routers and logit deciders (e.g. AnyJev) may *route* or *tighten* a decision (raise it to approval or block). They may never turn a deny or require-approval into an allow. `PolicyEngine` providers must declare `deterministic=True`. | Registry rejects non-deterministic policy providers; governor step 6 uses `tighten()` only; conformance suite |
| **R4** | **No silent gaps.** Adapters and runners declare the hook points they `reach`. Loading fails if the baseline needs a hook they can't reach. Unknown spec keys, unknown providers and unknown hook names also fail loading. | Loader reachability check; `extra="forbid"` on spec models |
| **R5** | **One owner per control.** Retries, fallbacks and tenant budgets belong to the gateway (LiteLLM) when one is configured, so SDK clients are built with retries off. Per-run budgets, deadlines and repair belong to the harness. | Plugin defaults; `harnessweaver doctor` flags duplicate owners |
| **R6** | **Small core.** The `harnessweaver` package depends only on `pydantic`, `opentelemetry-api`, `pyyaml`, `anyio` and `loguru` (ADR-0024). Every other dependency lives in a plugin, the CLI or the sidecar package. | CI test asserts the core dependency list |
| **R7** | **Contracts do not leak frameworks.** Hook payloads, ports, outcomes and wire contracts use only HarnessWeaver types (Pydantic models / JSON Schema). No OpenAI, Anthropic, Pydantic AI, LangChain or other third-party types cross a contract. | Review; contract models live in `core/` and `spec/` only |
| **R8** | **New guards start in shadow mode.** A guard is introduced with `mode: log_only` (the CLI scaffolds it that way) and promoted to `enforce` by a reviewed one-line spec change backed by eval evidence. | CLI default; `doctor` lists shadow guards; eval shadow report |
| **R9** | **No raw content before redaction.** Prompts, outputs, tool args and tool results never reach logs, spans or traces before redaction. `capture_content` is `false` by default, and when it is on, only post-redaction content is captured. | Telemetry module; conformance check "no raw content in logs" |
| **R10** | **Bounds are errors, not clamps.** A value outside its bound fails loading. Per-run overrides apply only to fields marked `overridable` and may only *lower* a value. | `spec/merge/bounds.py`; `merge` fixtures |
| **R11** | **Contracts first, in every language.** A change to hook points, outcomes, actions, the spec format or wire payloads starts in the contract models, JSON Schema and conformance fixtures. It isn't released until the fixtures pass in Python, TypeScript and the sidecar. Within a major `apiVersion`, changes are additive only. | Schema drift test; shared fixtures; CI runs both languages |
| **R12** | **Govern, don't compete.** The core has no planner, memory model, prompt templating language, vector store or open-ended agent loop. Only the bounded `direct` tool loop is allowed (see ADR-0011). Agent frameworks are integrated through adapters. | Review; ADR required for any exception |
| **R13** | **Every decision is observable.** Every route chosen, guard fired, tool allowed or denied, budget hit, approval and middleware failure emits a traced event with its reason. | Bus records every outcome; `assert_trace` in tests |
| **R14** | **Everything runs offline.** Every module, example and template runs against fakes with no network and no model spend. Live providers refuse to call out in test mode. | `HARNESSWEAVER_TEST_MODE=1`; examples run in CI offline |

---

## Coding rules

| ID | Rule |
| --- | --- |
| **C1** | Python `>=3.12`. Type everything. `pyright --strict` must pass on `core/` and `spec/`; the rest of the code must pass `standard` mode with no errors. |
| **C2** | Data that crosses a boundary (spec, contract, hook payload, provider config, wire message) is a Pydantic v2 model. Spec and config models use `extra="forbid"`. Contract value objects are `frozen=True`. |
| **C3** | Async first. Library code is `async` and uses `anyio`. No blocking I/O on the event loop; wrap sync work in `anyio.to_thread.run_sync`. |
| **C4** | No global mutable state. Registries and buses belong to a `Harness` instance. The process-wide plugin catalog is read-only after discovery. Time comes from the injected `Clock`, never `datetime.now()` inside logic. |
| **C5** | Only taxonomy errors (`harnessweaver.errors.HarnessError` subclasses) cross a public boundary. No bare `except:`. Never swallow an exception without recording it on the trace. |
| **C6** | Logging uses loguru: `from loguru import logger` (ADR-0024). Every package that logs disables its own name when it is imported (`logger.disable(__name__)` in its top-level `__init__`), so it stays silent until the app calls `logger.enable(...)`. Library code never calls `print` and never adds loguru sinks. Log messages never contain raw content (R9). |
| **C7** | Public API is exported only from `harnessweaver/__init__.py` (and plugin top-level packages). Everything else is internal and may change; modules prefixed `_` are always private. |
| **C8** | Names: hook points are dotted lowercase (`tool.before`); provider names are `vendor_or_area.capability` (`pii.regex`, `acme.pii`); spec keys are `snake_case`; env vars are `HARNESSWEAVER_*`. |
| **C9** | Every module, package, class, method and function has a docstring wherever possible (Google style), saying what it does, what it raises and which rule it upholds when relevant. Complex or long logic has enough comments that a reader can follow how it works and why: the approach, the steps, the non-obvious cases and the reasons. Comments don't narrate obvious single lines. |
| **C10** | No new third-party dependency without an ADR that names the package, the extra or plugin it lives in, and why the stdlib or an existing dependency isn't enough. |
| **C11** | Keep functions small and side-effect boundaries explicit. A provider must be constructible from its config model alone, with no hidden environment reads beyond those its config documents. |
| **C12** | TypeScript: `strict` mode, ESM only, Node `>=22`, no `any` in exported types, runtime validation for anything read from disk or the network. Behavior must match the Python reference through the shared fixtures. |

## Testing rules

| ID | Rule |
| --- | --- |
| **T1** | Every change ships with tests. A bug fix starts with a failing test that reproduces it. |
| **T2** | Tests run offline (R14): no network, no API keys, no model spend. Use `ScriptedModel`, `FakeTool`, `FakeDecider` and cassettes. |
| **T3** | Merge, outcome-combination and expression logic get Hypothesis property tests, not only examples. |
| **T4** | Any behavior defined by a contract gets a language-neutral JSON fixture under `contracts/fixtures/conformance/`, run by both Python and TypeScript. |
| **T5** | Every first-party provider and adapter passes the conformance suite (`--harnessweaver-conformance=<name>`). |
| **T6** | Examples and templates are tests: CI runs each example offline end to end, and `init` output from every template must pass its own tests. |
| **T7** | Coverage floor: 90% lines for `core/` and `spec/`, 80% for the rest of the core package. Coverage may not drop in a PR without a written reason. |
| **T8** | Async tests use the anyio pytest plugin (`@pytest.mark.anyio`). Don't sleep for time; inject a fake `Clock`. |

## Security rules

| ID | Rule |
| --- | --- |
| **S1** | Apps and providers never hold model provider keys when a gateway is configured. Keys come from the environment or the gateway, never from spec files. |
| **S2** | No tool runs without a manifest. Manifests pin `definition_digest`; a mismatch blocks the call (rug-pull defense). |
| **S3** | Tool output, retrieved context and anything from the network is labelled `untrusted`. The lethal-trifecta check (untrusted content + private data + external egress) runs on every `tool.before`. |
| **S4** | Code-executing tools run in a sandbox (`sandbox: monty` or stronger), never with `exec`/`eval` in the host process. The cel-lite evaluator never calls `eval`. |
| **S5** | Supply chain: lockfiles are committed; CI actions are pinned by commit SHA; container base images are pinned by digest; releases ship an SBOM and signed artifacts. |
| **S6** | The sidecar binds to `127.0.0.1` by default and requires a bearer token for every route except `/v1/health`. |
| **S7** | Secrets and personal data never appear in fixtures, cassettes, examples or logs. Use obviously fake values (`sk-test-...`, `alice@example.com`). |
| **S8** | Plugins are inert until used. Installing a plugin enables nothing; only names referenced by the effective spec are imported. Plugin modules do no I/O and register nothing at import time, and the org baseline can lock `plugins.allow`. |

## Documentation rules

| ID | Rule |
| --- | --- |
| **D1** | A change to public API, spec format, CLI or behavior updates the relevant docs page and the `CHANGELOG.md` of each package it changes (the root one for repository-wide changes) in the same commit. |
| **D2** | Diagrams are Mermaid, kept next to the text they explain, so they are reviewed like code. PNGs are only for diagrams that Mermaid can't express. |
| **D3** | Code in docs is either a tested example (included from `examples/`) or short enough to be checked by eye. Never document an API that doesn't exist yet without marking it *planned*. |
| **D4** | Any deviation from the design guide (`docs/AI Harness Framework Design and Build Guide.md`) is recorded as an ADR (in `docs/adr/`, indexed in DESIGNS.md No. 28) with its reason, and listed in DESIGNS.md No. 29. |
| **D5** | Use only characters found on a standard keyboard (printable ASCII) in docs, code, comments, fixtures and commit messages. Refer to numbered sections as `No. 13`, and write `-` for dashes, `->` for arrows and `...` for ellipses. Unicode test data is written as escapes (`\u00e9`). `make check` enforces this; the design guide is the only exception (D4). |

## Versioning rules

| ID | Rule |
| --- | --- |
| **V1** | Three version streams move independently: contracts (`apiVersion: harnessweaver/v1`), packages (SemVer per package) and profiles (SemVer; specs pin ranges like `@^2`). |
| **V2** | Within a contract major, changes are additive: new optional fields, new hook points, new actions. Removing or changing anything needs a new major `apiVersion`, and the previous major stays supported for 12 months. |
| **V3** | Tightening a baseline profile (a new lock, a narrower bound) is a breaking profile change and needs a major profile version. |
| **V4** | Deprecations warn for at least one minor release before removal, and are listed in the package's `CHANGELOG.md`. |
| **V5** | Every provider and adapter declares the contract range it supports (`contract=">=1.0,<2"`). The loader refuses incompatible combinations. |

## Git and commit rules

| ID | Rule |
| --- | --- |
| **G1** | **Never commit without explicit human approval.** AI agents finish a change, run the checks, summarize it and ask. A previous approval does not carry over to the next commit. |
| **G2** | Never push, force-push, rewrite published history or delete branches without explicit approval. |
| **G3** | One logical change per commit, using [Conventional Commits](https://www.conventionalcommits.org/) (`feat(core): add hook bus`, `docs: add RULES.md`). The body says *why* and cites rules or ADRs when relevant. |
| **G4** | Commit only source, docs, lockfiles and checked-in contract artifacts (`contracts/schemas`, `contracts/openapi`), which are drift-tested. Never commit `.venv`, caches, build output, secrets or local run state. |
| **G5** | `make check` (and `pnpm -C typescript test` when TypeScript changed) passes before asking for a commit. |
| **G6** | AI-assisted commits carry a `Co-Authored-By:` trailer naming the assistant. |

---

## Review checklist

Copy this into every pull request (it is also in `.github/PULL_REQUEST_TEMPLATE.md`).

- [ ] No invariant (R1-R14) is weakened; any rule exception has an ADR.
- [ ] Contract changes start in the models, schemas and fixtures, and pass in Python and TypeScript (R11, T4).
- [ ] New middleware declares `fail_mode`; baseline middleware is `closed` (R2).
- [ ] New guards ship with `mode: log_only` (R8).
- [ ] Nothing raw reaches logs or spans before redaction (R9).
- [ ] No new core dependency (R6); any new dependency has an ADR (C10).
- [ ] Tests are offline, cover the change, and include property tests or fixtures where relevant (T1-T4).
- [ ] Docs and the changed packages' `CHANGELOG.md` files are updated (D1), using only keyboard characters (D5).
- [ ] `make check` is green (G5); the commit is approved by a human (G1).
