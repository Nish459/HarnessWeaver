# Changelog: harnessweaver-cli

All notable changes to the `harnessweaver` command and its project templates. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this package uses [Semantic Versioning](https://semver.org/) on its own (RULES V1). Versions before 0.7.1 were never published; their Git tags (`harnessweaver-cli@<version>`) mark the commit where each one landed.

## [Unreleased]

## 0.7.2 - 2026-11-08

### Changed

- `harnessweaver init` ends with next steps that work right after `uvx --from harnessweaver-cli harnessweaver init`, with nothing installed yet: `uv sync`, then `uv run harnessweaver spec validate --env offline` and `uv run harnessweaver test`. The templates' READMEs run their commands the same way, and the package's README uses absolute links, which work on PyPI.

### Fixed

- A template's `app/main.py` now prints why a run didn't complete, as `error: <code>: <message>` (for example `error: provider_error: openai.chat needs $LITELLM_API_KEY`), and the `chat` template's terminal app shows the reason next to the status. A first run against a real model with no key or no gateway printed only `status: failed` and `output: None`.

## 0.7.1 - 2026-11-01

The first version published to PyPI.

### Added

- The package ships the Apache-2.0 `LICENSE` in its wheel and sdist.

## 0.7.0 - 2026-11-01

### Added

- `harnessweaver sidecar --max-body-bytes`: the largest request body harnessd reads, 10 MiB by default.

## 0.6.2 - 2026-11-01

### Security

- `spec diff git:<ref>:<path>` read profiles from the working tree, so a pull request that weakened only a profile showed no difference. A `git:` side is now loaded from that ref's own tree, the ref can't be read as a git option, and the diff lists profile layers added and removed.

## 0.6.1 - 2026-10-25

### Fixed

- The `chat` template's terminal app ends the chat at the end of input (Ctrl-D, or piped input running out) instead of raising `EOFError`.

## 0.6.0 - 2026-10-20

### Added

- `harnessweaver gateway litellm` writes a LiteLLM Proxy config from the spec (gateway models, aliases, retries, a timeout from the longest deadline, message logging off, the `otel` callback, and a tool-permission guardrail that allows only tools whose manifests need no run), and `harnessweaver gateway mcp` writes the neutral `tool-allow-list` for an MCP gateway: each allowed tool's server, digest and scopes, and every withheld tool with its reason (ADR-0039).
- `harnessweaver dev [--up]` writes a local Compose stack into `.harness/dev/` (LiteLLM, an OpenTelemetry collector, Langfuse and harnessd, digest-pinned and on 127.0.0.1 only) with local secrets generated once into `.env`, and starts it.

## 0.5.0 - 2026-10-20

### Added

- `harnessweaver sidecar [SPEC]` runs harnessd.

## 0.4.0 - 2026-10-20

### Added

- `harnessweaver add guard` adds a guard in shadow mode (`mode: log_only`, R8), and `harnessweaver add tool` writes a tool manifest from a function's signature and Google-style docstring and adds its directory to `tools.manifests`. Both edit `harness.yaml` with its comments kept (ruamel.yaml, ADR-0016), and a guard whose edit doesn't load is taken back out.
- `harnessweaver tools pin` writes each manifest's `definition_digest` (S2); `--tool` pins one.
- `harnessweaver plugin new <namespace>` scaffolds a standalone plugin package (entry point, `hw.Plugin`, a sample `<namespace>.banned_words` guard, and tests whose `pytest` run includes the conformance suite), and `harnessweaver plugin list` shows installed plugins with their versions, contract ranges and compatibility.
- Project templates `rag`, `agent` (a Pydantic AI agent with governed tools and a red-team eval set), `workflow` and `chat`, each passing its own tests offline (T6).

### Changed

- `harnessweaver init` refuses template names starting with `_`, which are scaffolds for other commands.

## 0.3.0 - 2026-10-20

### Added

- `harnessweaver eval run` (baselines in `.harness/baselines/<task>.<suite>.json`, `--update-baseline`, the shadow-guard report; exit 1 on a missed threshold or a regression, 2 when the suites can't run) and `harnessweaver eval report` (online samples).
- `harnessweaver policy test` checks a table of calls against `Harness.authorize` (`policy_tests.yaml`; exit 1 on a mismatch, 2 when the tests can't run).
- `harnessweaver replay <run_id>` runs a recorded run again against the current code and spec (exit 1 when the status or output changed).

### Changed

- The extraction template's offline overlay answers every golden case, so `harnessweaver eval run -e offline` passes on it, and it tests its golden set.

## 0.2.0 - 2026-10-19

### Added

- `harnessweaver doctor` warns about tool manifests without a pinned digest (printing the digest to pin) and fails ones that changed since they were pinned.

## 0.1.0 - 2026-10-18

### Added

- The `harnessweaver` command with `init` (built-in and plugin templates), `spec validate`, `spec explain`, `spec diff` (either side can be `git:<ref>:<path>`), `doctor` (level and next steps, reachable hooks, duplicate retry owners, unpinned profiles, shadow guards, content capture), `hooks`, `test` (offline, test mode on) and `contracts export`.
- The `extraction` project template, whose output passes its own tests (T6).
