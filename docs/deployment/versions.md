# Versioning

Three things are versioned independently, each with its own rules (RULES V1): the **contracts**, the **packages**, and the **profiles**.

| Versioned thing | Scheme | A breaking change means | Support window |
| --- | --- | --- | --- |
| Contracts (`harnessweaver/v1`) | A major in the `apiVersion` string; minor additions only | Removing or changing a field, hook point or action | The previous major is supported for 12 months after the next ships |
| Packages (core, CLI, sidecar, plugins, TypeScript) | SemVer, per package | A change to the public Python or TypeScript API | The latest two minor versions get patches |
| Profiles (built-in and org) | SemVer; specs pin a range such as `@^2` | Adding a lock or tightening a bound | The org decides; `spec diff` shows the impact |

## Contracts

The contract is everything that crosses a boundary: the spec format, hook points and their payloads, outcomes and guard actions, the wire API, and the behavior pinned by the conformance fixtures ([Contracts](../reference/contracts.md)).

- Within `harnessweaver/v1`, changes are **additive only**: new optional fields, new hook points, new actions (V2).
- Anything else needs an ADR and a new major `apiVersion`, and the previous major stays supported for 12 months.
- A contract change isn't released until Python, TypeScript and the sidecar all pass the fixtures (R11).

## Packages and plugins

Each package is released on its own, and its Git tag is `<package>@<version>`, such as `harnessweaver@0.2.0` or `@harnessweaver/core@0.2.0`.

Every provider, runner, adapter and plugin declares the contract range it supports (`contract=">=1.0,<2"`), and the loader refuses an incompatible combination with `IncompatibleContract` (V5). So a plugin built against `harnessweaver/v1` keeps working with any core release that implements v1, whatever the packages' own version numbers. `harnessweaver plugin list` shows each installed plugin's range and whether it is compatible.

Deprecations warn for at least one minor release before removal, and are listed in the package's [changelog](../release-notes/index.md) (V4).

## Profiles

- Built-in profiles and org profiles carry `metadata.version`.
- Specs pin org profiles with a range (`org://acme-baseline@^1`). `harnessweaver doctor` warns about unpinned ones.
- **Tightening a baseline is a breaking change** for the apps that extend it: a new lock or a narrower bound is a major version (V3). Loosening it (allowing another plugin, raising a bound) is a minor one.
- Publish a new major alongside the old one, so apps move when they are ready: `acme-baseline@1.4.0.yaml` and `acme-baseline@2.0.0.yaml` can sit in the same profile directory.

## Upgrading safely

1. Read the changelog for the versions you skip.
2. Upgrade the packages (`uv lock --upgrade-package harnessweaver ...`).
3. Run `harnessweaver spec validate` and `doctor` for every environment, then the tests, `eval run` and `policy test`.
4. For a baseline upgrade, run `harnessweaver spec diff` between the old and new effective spec, and review new locks, bounds and the level.
5. For behavior changes in production paths, replay recorded runs against the new version (`harnessweaver replay`).
