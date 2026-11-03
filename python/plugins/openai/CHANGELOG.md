# Changelog: harnessweaver-openai

All notable changes to this plugin. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this package uses [Semantic Versioning](https://semver.org/) on its own (RULES V1). Versions before 0.2.0 were never published; their Git tags (`harnessweaver-openai@<version>`) mark the commit where each one landed.

## [Unreleased]

## 0.2.0 - 2026-11-02

The first version published to PyPI.

### Added

- The README says what `openai.chat` doesn't carry for Claude: thinking, `effort` and server-side refusal fallbacks.
- `hold_stream` delivers a streamed answer's chunks only once it has finished, so nothing from a declined answer reaches the app.
- `block_empty_answers` treats an answer with no text and no tool calls as declined, which catches a streamed refusal LiteLLM dropped.

### Fixed

- A request the model declines (the message's `refusal` field, also under `provider_specific_fields` where LiteLLM moves it, or the finish reason `content_filter`) now ends the run `blocked` with code `model_refusal`, in `openai.chat` and through `harness.instrument(client)`, and its usage and cost still count. It used to pass as an ordinary answer, often empty. An app that reads `message.refusal` on an instrumented client now gets `RunBlocked` instead. Needs `harnessweaver` 0.18.0.

## 0.1.2 - 2026-11-01

### Added

- The package ships the Apache-2.0 `LICENSE` in its wheel and sdist.

## 0.1.1 - 2026-10-18

### Added

- The adapter gives the conformance suite an offline sample call, so `make conformance` checks it (T5).

## 0.1.0 - 2026-10-18

### Added

- The `openai.chat` provider (retries off, LiteLLM cost header, streaming) and the `instrument()` adapter for `OpenAI` / `AsyncOpenAI`.
