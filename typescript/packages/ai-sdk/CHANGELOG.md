# Changelog: @harnessweaver/ai-sdk

All notable changes to this package. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this package uses [Semantic Versioning](https://semver.org/) on its own (RULES V1). Versions before 0.2.0 were never published; their Git tags (`@harnessweaver/ai-sdk@<version>`) mark the commit where each one landed.

## [Unreleased]

## 0.2.0 - 2026-11-02

The first version published to npm.

### Added

- `holdStream` delivers a stream's parts only once it has finished, so nothing from a declined answer reaches the app.
- `blockEmptyAnswers` treats an answer with no text and no tool calls as declined, for a provider that drops the refusal.

### Fixed

- An answer with the finish reason `content-filter` now throws `ModelRefusal`, from the call or the stream, and the run ends `blocked` with code `model_refusal` and its usage and cost counted. It used to pass as an ordinary answer. Needs `@harnessweaver/core` 0.5.0.

## 0.1.1 - 2026-11-01

### Added

- The package ships the Apache-2.0 `LICENSE` in its tarball.

### Fixed

- The package's README no longer says it isn't published.

## 0.1.0 - 2026-10-23

### Added

- `wrapModel(session, model)` (and `harnessMiddleware`) govern AI SDK v7 models: allowed aliases and budgets, `model.before` redactions written back into the prompt, `model.after` redactions in the answer, usage and cost, and `stream.chunk` on each streamed text delta.
