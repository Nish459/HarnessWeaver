# Python API

The public Python API, generated from its docstrings. Everything here is exported from `harnessweaver` (`import harnessweaver as hw`), or from the public modules `harnessweaver.errors`, `harnessweaver.ports`, `harnessweaver.adapters` and `harnessweaver.testing`. Anything else, and every module whose name starts with `_`, is internal and may change between releases (RULES C7).

| Page | Covers |
| --- | --- |
| [Harness and Session](harness.md) | `hw.load`, `Harness` (runs, approvals, sessions, evals, replay, instrument and wrap), `Session` |
| [Results and traces](results.md) | `RunResult`, `RunStatus`, `RunEvent`, `RunTrace`, `TraceEvent` |
| [Middleware and outcomes](middleware.md) | `@hw.middleware`, the outcomes, hook points, bands and hook events |
| [Plugins and ports](plugins.md) | `hw.Plugin`, `@hw.provider`, `@hw.decider`, `@hw.runner`, `@hw.adapter`, and the port Protocols |
| [Contracts](contracts.md) | Messages, the envelope, decisions, guards, policy, tools, context and approvals |
| [Evals and replay](evals.md) | Eval datasets and results, baselines, online samples, replay reports |
| [Specs](spec.md) | `hw.load_spec`, `EffectiveSpec`, `HarnessSpec`, `Level` |
| [Errors](errors.md) | The error taxonomy |
| [Testing](testing.md) | `harness_for_test`, scripted models, fakes, trace and leak assertions, cassettes |

The TypeScript API mirrors it: see [TypeScript](../../advanced/typescript.md).
