# Changelog: harnessweaver-monty

All notable changes to this plugin. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this package uses [Semantic Versioning](https://semver.org/) on its own (RULES V1). Versions before 0.2.1 were never published; their Git tags (`harnessweaver-monty@<version>`) mark the commit where each one landed.

## [Unreleased]

## 0.2.1 - 2026-11-01

The first version published to PyPI.

### Added

- The package ships the Apache-2.0 `LICENSE` in its wheel and sdist.

## 0.2.0 - 2026-10-26

### Removed

- `MontySandboxConfig` and its `grace` setting: harnesses build sandboxes with no settings, so it could never be set. The 2s grace is now a constant, and `monty.sandbox` takes no settings.

## 0.1.0 - 2026-10-19

### Added

- The `monty.sandbox` sandbox, running code tools in pydantic-monty workers with time and memory limits.
