# Changelog: @harnessweaver/core

All notable changes to the TypeScript core. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this package uses [Semantic Versioning](https://semver.org/) on its own (RULES V1). Versions before 0.4.1 were never published; their Git tags (`@harnessweaver/core@<version>`) mark the commit where each one landed.

## [Unreleased]

## 0.5.0 - 2026-11-02

### Added

- `ModelRefusal`, a `RunBlocked` with code `model_refusal` for a model that declined. Its `response` carries what the call used. `run.generate` counts it and notes it on the trace (RULES R13), and `run.refuseModelCall` does the same for a call made outside `generate`, such as a stream. Neither runs `model.after`.

## 0.4.1 - 2026-11-01

The first version published to npm.

### Added

- The package ships the Apache-2.0 `LICENSE` in its tarball.

### Fixed

- The package's README no longer says it isn't published.

## 0.4.0 - 2026-11-01

### Added

- Specs accept `approvals.grant_scope` (ADR-0045).

### Security

- An approval given for another step's ask no longer satisfies a role the approver doesn't hold. Governor step 7 checks the manifest's `approver_role`, else the task's, else the spec's (ADR-0045).

## 0.3.0 - 2026-11-01

### Security

- Guards never saw JSON object keys, and `pii_redact` and `strip_instructions` skipped them, so an object keyed by e-mail address reached the model and a secret in a key passed `secrets.scan`. Keys are now checked and redacted like values. Keys that redact to one name stay distinct (`[EMAIL]`, `[EMAIL]#2`), so no entry is lost. **Changed:** a guard also sees field names.

## 0.2.0 - 2026-11-01

### Security

An app's team could shed org baseline controls with files in its own repository. These all fail loading now (R1, R2, R10, ADR-0043):

- Wildcard locks (`guardrails.input[*]`, `tasks.*.budget`) were never enforced. They now cover every key or item, including ones added later.
- A profile in the app's `.harness/profiles` with a higher version replaced the platform's baseline of the same name. The first directory on the search path holding a name now owns it, and versions are never compared across directories. **Changed:** a platform that splits versions of one name across directories must keep them together.
- A profile the app listed before its baseline could put keys into items the baseline then locked. Profiles the app's team can write now merge after the platform's.
- An app file with the same reference text as a platform profile's parent displaced that parent. Profiles are now told apart by file, for duplicates and cycles, so the same relative text in two directories is no longer called a cycle.
- `null` at a path with a `max` bound removed the limit and passed the bound. It's now a `BoundViolation`.
- A baseline guard that fails open passed the R2 check when it sat in a parallel group with a closed one. Each guard is now checked. **Changed:** such a baseline now fails loading.
- An item with the merger's temporary id (`~autoN~`) could edit a locked item that had no id. Those ids are now reserved.
- A locked `where: sidecar` guard followed an unlocked `sidecar.url`, so a later layer could repoint it. **Changed:** a baseline that locks such a guard must now lock `sidecar.url` too.
- The JSON Schema validator skipped keys named after `Object.prototype` members (`constructor`, `toString`), in specs and in tool arguments, and NaN passed bounds and budgets. Own keys only are now checked, non-finite numbers are refused, and a `__proto__` key in a spec layer fails.

## 0.1.0 - 2026-10-23

### Added

- The TypeScript core (ADR-0040): it loads the same `harness.yaml` (layers, locks, bounds, built-in and org profiles, overlays, levels) and runs the hook bus, budgets and cost, the built-in guards, cel-lite policy and validation rules, the `rules` and `lexical` routing stages, the tool governor for tools given in code, the `memory` context provider, versioned prompts and the eval graders, in `harness.session(...)`.
- Plugins register with `definePlugin`.
- `SidecarClient` calls every harnessd route, and guards declared `where: sidecar` run there.
- It passes every suite in `contracts/fixtures/conformance/`, and Example 02's spec behaves as it does in Python.
