# Changelog: harnessweaver-anthropic

All notable changes to this plugin. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this package uses [Semantic Versioning](https://semver.org/) on its own (RULES V1). Versions before 0.2.0 were never published; their Git tags (`harnessweaver-anthropic@<version>`) mark the commit where each one landed.

## [Unreleased]

### Fixed

- With no `api_key_env` and no credentials for the SDK to find (no `ANTHROPIC_API_KEY` or `ANTHROPIC_AUTH_TOKEN`, no `ant auth login` profile, no workload identity), a call failed with `the model provider failed (TypeError)`. It now fails with `anthropic.messages found no credentials`, saying what to set. A profile or identity token the SDK was pointed at but can't load fails with the SDK's own message, which names the file or variable, instead of `the model provider failed (CredentialsError)`.

## 0.2.0 - 2026-11-02

The first version published to PyPI.

### Added

- `hold_stream` delivers a streamed answer's chunks only once it has finished, so nothing from a declined answer reaches the app.

### Fixed

- A request the model declines still counts its usage and cost in the run, and the refusal is noted on the trace (RULES R13). It raises `ModelRefusal`, still a `RunBlocked` with code `model_refusal`. Needs `harnessweaver` 0.18.0.

## 0.1.2 - 2026-11-01

### Added

- The package ships the Apache-2.0 `LICENSE` in its wheel and sdist.

## 0.1.1 - 2026-10-18

### Added

- The adapter gives the conformance suite an offline sample call, so `make conformance` checks it (T5).

## 0.1.0 - 2026-10-18

### Added

- The `anthropic.messages` provider (adaptive thinking, `effort`, server-side refusal fallbacks on by default, thinking blocks replayed unchanged across a tool loop, streaming) and the `instrument()` adapter for `Anthropic` / `AsyncAnthropic`.
