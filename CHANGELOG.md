# Changelog

All notable changes to the HarnessWeaver packages are recorded here. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and every package uses [Semantic Versioning](https://semver.org/) independently (RULES V1).

## [Unreleased]

### Added

- uv workspace with the core package `harnessweaver`, the developer tooling `harnessweaver-cli` (the `harnessweaver` command; `--version` so far), the sidecar `harnessweaver-sidecar` (`harnessd`; `GET /v1/health` so far), and package skeletons for the first-party plugins `harnessweaver-openai`, `harnessweaver-anthropic`, `harnessweaver-pydantic-ai`, `harnessweaver-monty`, `harnessweaver-otel` and `harnessweaver-cel`.
- Core extras that pull in first-party plugins: `harnessweaver[openai]`, `[anthropic]`, `[pydantic-ai]`, `[monty]`, `[otel]`, `[cel]`, `[cli]`, `[sidecar]` and `[all]`.
- A test that keeps the core's runtime dependencies to `pydantic`, `opentelemetry-api`, `pyyaml` and `anyio` (RULES R6).
- `make check` (ruff, ruff format, pyright, pytest), CI on Python 3.12–3.14 with SHA-pinned actions, pre-commit hooks and a pull request template.
