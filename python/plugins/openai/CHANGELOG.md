# Changelog: harnessweaver-openai

All notable changes to this plugin. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this package uses [Semantic Versioning](https://semver.org/) on its own (RULES V1). Versions before 0.1.2 were never published; their Git tags (`harnessweaver-openai@<version>`) mark the commit where each one landed.

## [Unreleased]

## 0.1.2 - 2026-11-01

The first version published to PyPI.

### Added

- The package ships the Apache-2.0 `LICENSE` in its wheel and sdist.

## 0.1.1 - 2026-10-18

### Added

- The adapter gives the conformance suite an offline sample call, so `make conformance` checks it (T5).

## 0.1.0 - 2026-10-18

### Added

- The `openai.chat` provider (retries off, LiteLLM cost header, streaming) and the `instrument()` adapter for `OpenAI` / `AsyncOpenAI`.
