# Changelog: harnessweaver-otel

All notable changes to this plugin. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this package uses [Semantic Versioning](https://semver.org/) on its own (RULES V1). Versions before 0.2.1 were never published; their Git tags (`harnessweaver-otel@<version>`) mark the commit where each one landed.

## [Unreleased]

## 0.2.1 - 2026-11-01

The first version published to PyPI.

### Added

- The package ships the Apache-2.0 `LICENSE` in its wheel and sdist.

## 0.2.0 - 2026-10-19

### Changed

- Logging goes through loguru (ADR-0024). The plugin is silent until the app opts in with `logger.enable("harnessweaver_otel")`, and never adds sinks.

## 0.1.0 - 2026-10-18

### Added

- The `otel.sdk` provider, which sets up the OpenTelemetry SDK with a console or OTLP exporter when `observability.configure_sdk: true` and leaves an app's own setup alone (R5).
