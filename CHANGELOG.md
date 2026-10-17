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
- JSON Schemas for every contract under `contracts/schemas`, with `make schemas` / `make schemas-check` and a drift test (ADR-0005).
- Language-neutral conformance fixtures under `contracts/fixtures/conformance` (suites `durations`, `semver`, `outcomes`, `hook_order`, `expr`) and their Python runners.
- Hypothesis property tests for outcome combination, cel-lite arithmetic and logic, durations and versions (T3).
- uv workspace with the core package `harnessweaver`, the developer tooling `harnessweaver-cli` (the `harnessweaver` command; `--version` so far), the sidecar `harnessweaver-sidecar` (`harnessd`; `GET /v1/health` so far), and package skeletons for the first-party plugins `harnessweaver-openai`, `harnessweaver-anthropic`, `harnessweaver-pydantic-ai`, `harnessweaver-monty`, `harnessweaver-otel` and `harnessweaver-cel`.
- Core extras that pull in first-party plugins: `harnessweaver[openai]`, `[anthropic]`, `[pydantic-ai]`, `[monty]`, `[otel]`, `[cel]`, `[cli]`, `[sidecar]` and `[all]`.
- A test that keeps the core's runtime dependencies to `pydantic`, `opentelemetry-api`, `pyyaml` and `anyio` (RULES R6).
- `make check` (ruff, ruff format, pyright, pytest), CI on Python 3.12-3.14 with SHA-pinned actions, pre-commit hooks and a pull request template.
- `make check` also rejects characters that aren't on a standard keyboard (`scripts/check_ascii.py`, RULES D5).
