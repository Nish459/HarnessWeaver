# Changelog: harnessweaver-pydantic-ai

All notable changes to this plugin. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this package uses [Semantic Versioning](https://semver.org/) on its own (RULES V1). Versions before 0.1.2 were never published; their Git tags (`harnessweaver-pydantic-ai@<version>`) mark the commit where each one landed.

## [Unreleased]

## 0.1.2 - 2026-11-01

The first version published to PyPI.

### Added

- The package ships the Apache-2.0 `LICENSE` in its wheel and sdist.

## 0.1.1 - 2026-11-01

### Security

- A Pydantic AI agent's tool with a harness manifest was offered to the model with the agent's own definition, so a third-party toolset could change what a reviewed tool told the model. `HarnessCapability` now offers the manifest's description and schema. The agent's own handler still runs, and a same-named tool isn't proved to behave as reviewed: review or prefix a toolset's tool names, and close the schema to refuse undeclared arguments.

## 0.1.0 - 2026-10-20

### Added

- The `pydantic_ai.agent` runner (the spec's models or the agent's own, the task's prompt and tools, `deps`, repairs as `ModelRetry`, approvals that suspend and resume through Pydantic AI's deferred tools, including tools marked `requires_approval=True`) and the `wrap()` adapter for Pydantic AI agents, both governing through `HarnessCapability` (ADR-0037). `make conformance` covers it.
