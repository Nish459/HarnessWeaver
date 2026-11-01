# Changelog: harnessweaver-cel

All notable changes to this plugin. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this package uses [Semantic Versioning](https://semver.org/) on its own (RULES V1). Version 0.1.0 was never published; its Git tag (`harnessweaver-cel@0.1.0`) marks the commit where it landed.

## [Unreleased]

## 0.1.1 - 2026-11-01

The first version published to PyPI.

### Added

- The package ships the Apache-2.0 `LICENSE` in its wheel and sdist.

## 0.1.0 - 2026-10-19

### Added

- The `cel.policy` engine, full CEL through cel-python, checked against the shared policy fixtures; its tests pin every `expr` fixture where full CEL and cel-lite differ.
