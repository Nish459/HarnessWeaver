# Conformance

Every plugin can run the same conformance suite the first-party plugins pass (RULES T5). It checks the promises a plugin makes to the apps that use it: it loads lazily and quietly, builds from its config, answers with valid contracts, is as deterministic and fast as it says, fails closed when told to, and never leaks content.

```bash
uv run pytest --harnessweaver-conformance=acme                 # an installed plugin, by namespace
uv run pytest --harnessweaver-conformance=app.harness_plugin:plugin   # an in-repo plugin
uv run pytest --harnessweaver-conformance=harnessweaver        # the core's built-in plugin
uv run pytest --harnessweaver-conformance=acme,openai          # several
```

Installing `harnessweaver` adds a pytest plugin (through the `pytest11` entry point). It does nothing unless asked: `--harnessweaver-conformance` collects the suite for the named plugins. The checks are plain functions in `harnessweaver.testing.conformance`, so they also run outside pytest. A plugin scaffolded by `harnessweaver plugin new` runs the suite as part of its own tests.

## The checks

| Check | Applies to |
| --- | --- |
| Metadata: the entry point, the contract range (V5), names inside the namespace, profiles and templates that exist | the plugin |
| Importing it opens no sockets, writes no files and installs no global OpenTelemetry provider (S8) | the plugin |
| It builds from its config model alone, or from its declared `sample` settings (C11) | every contribution |
| Results validate against the port's contract; a state store also passes a round-trip contract | guardrails, deciders, model providers, state stores |
| Fresh instances give the same results for the same input | `deterministic=True` providers |
| A guard that runs past its timeout blocks when it fails closed, and can be cancelled | guardrails |
| A canary string passed through never reaches logs, spans or traces (R9) | guardrails, model providers |
| p95 latency within the declared class: `fast` 25 ms, `medium` 250 ms, `slow` 5 s | guardrails, deciders, offline model providers, state stores |
| It answers every declared hook with an outcome, never by raising | middleware |
| A task runs to a final state and fires only hooks the runner declares (R4) | runners |
| One call fires every declared hook (except conditional ones such as `run.error`), in lifecycle order (R4) | adapters |

## Making a plugin testable

- **Settings.** A contribution whose config has required fields declares `sample={...}` in its decorator, so the suite can build it.
- **Adapters.** Declare `sample=`, a function returning an `AdapterSample(target, call)`: an offline target and one call through it.
- **Live providers.** A provider that calls the network must refuse in test mode (`HARNESSWEAVER_TEST_MODE=1`, which the suite sets); the suite counts that refusal as passing for its call-based checks (R14).
- **Determinism.** Don't claim `deterministic=True` for anything that samples, calls a model or depends on time.
- **Latency.** Pick the class that holds at p95 on a CI machine; a provider that calls a service is `medium` or `slow`.

## In CI

The repository runs `make conformance` (the core plus every first-party plugin) as part of `make check`. Run the suite in your plugin's CI on every supported Python version, and pin `harnessweaver` to the contract range you declare.

## Language-neutral fixtures

Behavior that is part of the contract itself (the hook bus, outcomes, merging, levels, cel-lite, durations, versions, budgets, built-in guards, the governor, routing, evals) is pinned by JSON fixtures that the Python and TypeScript implementations both pass (R11, T4). See [Contracts](contracts.md#conformance-fixtures).
