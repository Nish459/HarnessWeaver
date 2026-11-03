# The spec

An app's harness is declared in a **spec**, usually `harness.yaml` next to the app's code. The spec selects modules and providers, sets the app's controls, and defines its tasks. It is merged with the framework defaults, any profiles it extends (such as the org baseline), and an environment overlay, then validated, before anything runs.

```python
import harnessweaver as hw

harness = hw.load("harness.yaml")                                  # overlay from $HARNESSWEAVER_ENV
harness = hw.load("harness.yaml", env="prod", profile_dirs=[Path("/etc/acme/profiles")])
```

```ts
import { load } from "@harnessweaver/core";

const harness = load("harness.yaml", { env: "prod", profileDirs: ["/etc/acme/profiles"] });
```

Loading fails with a `SpecError` subclass if anything is wrong: an unknown key, provider or hook name, a broken lock or bound, a level below the required one, an expression that doesn't compile, or a hook the runner can't reach (RULES R4). Nothing is checked lazily in the middle of a run. `harnessweaver spec validate` loads a spec exactly the same way.

## A minimal spec

```yaml
apiVersion: harnessweaver/v1
kind: Harness
metadata:
  name: ticket-triage                # lowercase letters, digits, '.', '_' and '-'
  owner: support-platform
extends: ["profile://extraction"]    # optional: profiles merged before this file

models:
  provider: openai.chat
  base_url: http://localhost:4000
  api_key_env: LITELLM_API_KEY
  default: fast
  aliases: { fast: fast-chat }

tasks:
  extract:
    runner: direct
    input: app.models:Message
    output: app.models:TicketSummary
    prompt: extract@1
    budget: { max_model_calls: 3, max_usd: 0.05 }
```

Everything else has a safe default from the framework's `defaults` profile: no telemetry export and no content capture, tool manifests required, one repair for invalid output, the `cel_lite` policy engine allowing by default, in-memory approvals with a 24 hour timeout, and an in-memory state store ([Built-in profiles](../reference/profiles.md)).

## Documents

| Document | `kind` | Allowed top-level keys |
| --- | --- | --- |
| App spec (`harness.yaml`) | `Harness` | `apiVersion`, `kind`, `metadata`, `extends`, and the sections |
| Profile (built-in, plugin or org) | `Profile` | The same, plus `locks`, `bounds` and `require_level` |
| Environment overlay (`harness.<env>.yaml`) | `Overlay` (optional) | Sections only: no `metadata`, `extends`, `locks`, `bounds` or `require_level` |
| Tool manifest (`*.tool.yaml`) | `Tool` | `apiVersion`, `kind`, `metadata`, `spec` ([Tool manifests](../reference/tool-manifests.md)) |
| Eval dataset | - | `suite`, `task`, `graders`, `thresholds`, `cases` ([Evals](../tutorial/evals.md#a-golden-set)) |

`apiVersion` is `harnessweaver/v1` for every document. Any key that isn't listed fails loading, as does an unknown key inside a section (R4).

## YAML rules

Specs are read as **YAML 1.2 with the core schema**, the same way in every language:

- Only `true` and `false` are booleans: `yes`, `no`, `on` and `off` stay strings.
- There are no implicit dates or sexagesimal numbers: `2026-01-05` and `1:30` stay strings.
- `012` is the decimal number 12.
- A repeated key in a map is an error.

## The sections

| Section | What it configures | Reference |
| --- | --- | --- |
| `metadata` | The app's name, owner, risk tier and description | [metadata](../reference/spec.md#metadata) |
| `extends` | The profiles merged before this file | [Layers](../advanced/layers.md#profiles) |
| `plugins` | In-repo plugins (`local`) and the namespaces apps may use (`allow`) | [plugins](../reference/spec.md#plugins) |
| `models` | The model provider, aliases, allowed aliases and prices | [models](../reference/spec.md#models), [Models](../tutorial/models.md) |
| `routing` | Routers: options, a cascade of stages, a default | [routing](../reference/spec.md#routing), [Routing](../tutorial/routing.md) |
| `context` | Retrieval sources and their governance | [context](../reference/spec.md#context), [Context and memory](../tutorial/context.md) |
| `memory` | The key-value store behind `s.memory` | [memory](../reference/spec.md#memory) |
| `guardrails` | Guards per stage: `input`, `context`, `tool_result`, `output`, `stream` | [guardrails](../reference/spec.md#guardrails), [Guardrails](../tutorial/guardrails.md) |
| `validation` | Repairs, what happens when they run out, business rules | [validation](../reference/spec.md#validation), [Validation](../tutorial/validation.md) |
| `tools` | Manifests, the trifecta rule, approval by risk, an optional judge | [tools](../reference/spec.md#tools), [Tools](../tutorial/tools.md) |
| `policy` | The policy engine and its rules | [policy](../reference/spec.md#policy), [Policy](../tutorial/policy.md) |
| `approvals` | The approval channel, timeout and default approver role | [approvals](../reference/spec.md#approvals), [Approvals](../tutorial/approvals.md) |
| `budgets` | Per-run limits | [budgets](../reference/spec.md#budgets) |
| `state` | The state store, and whether runs are recorded for replay | [state](../reference/spec.md#state), [State and replay](../tutorial/state.md) |
| `observability` | Telemetry export and content capture | [observability](../reference/spec.md#observability), [Observability](../tutorial/observability.md) |
| `evals` | Eval suites per task, and online sampling | [evals](../reference/spec.md#evals), [Evals](../tutorial/evals.md) |
| `middleware` | Middleware from plugins, with bands and hooks | [middleware](../reference/spec.md#middleware) |
| `tasks` | Named units of work: runner, types, prompt, model, tools, budget, approvals, guards | [tasks](../reference/spec.md#tasks) |
| `prompts` | Where versioned prompts live | [prompts](../reference/spec.md#prompts) |
| `sidecar` | Where harnessd is, for guards declared `where: sidecar` | [sidecar](../reference/spec.md#sidecar) |
| `require_level`, `locks`, `bounds` | Profiles only: the org's required level, locked paths, numeric bounds | [Layers](../advanced/layers.md) |

## Sections that pick a provider

Sections and items that choose a provider with `use:` keep the provider's own settings next to it: guards, routing stages, context sources, middleware, runners, `models`, `policy`, `approvals`, `state`, `memory`, `observability` and `tools.judge`. Every key HarnessWeaver doesn't own is passed to the provider, and validated against the provider's config model when the harness loads, so a misspelled setting still fails (R4).

```yaml
guardrails:
  input:
    - id: pii                  # HarnessWeaver's keys: id, use, action, mode, where, parallel,
      use: pii.regex           #   fail_mode, timeout, enabled
      action: redact
      entities: [EMAIL, PHONE] # pii.regex's own settings
      replacement: "<{entity}>"
```

Names in `use:` are `<namespace>.<name>` for plugin contributions (`openai.chat`, `acme.pii`). The core's own providers use bare names (`direct`, `memory`) or reserved area names (`pii.regex`, `cel_lite`, `lexical`).

## Files next to the spec

Relative paths in a spec are resolved against the directory of the file that names them: `tools.manifests` globs, `prompts.dir`, `extends` file paths, and the `file:` setting of routing stages and context sources. The `sqlite` state store's `path` is the exception: it is relative to the working directory.

```text
my-app/
  harness.yaml            the app spec
  harness.offline.yaml    an overlay, applied with HARNESSWEAVER_ENV=offline
  harness.prod.yaml       another overlay
  prompts/extract@1.md    versioned prompts (prompts.dir)
  tools/*.tool.yaml       tool manifests (tools.manifests)
  evals/golden.yaml       eval datasets (evals.<task>)
  .harness/profiles/      org profiles, if not on HARNESSWEAVER_PROFILE_PATH
  .harness/baselines/     eval baselines, committed
```

## Editor support

The JSON Schemas of complete documents are in [`contracts/schemas/`](https://github.com/Wise-DreamerZ/HarnessWeaver/tree/main/contracts/schemas): `harness.schema.json`, `profile.schema.json`, `tool-manifest.schema.json` and `eval-dataset.schema.json`. With the YAML language server (VS Code's YAML extension, for example), point a file at one:

```yaml
# yaml-language-server: $schema=https://raw.githubusercontent.com/Wise-DreamerZ/HarnessWeaver/main/contracts/schemas/harness.schema.json
apiVersion: harnessweaver/v1
```

Profiles and overlays are partial, so an editor may flag a profile that only tweaks part of a section; the loader is the authority.

## Checking a spec

| Command | What it does |
| --- | --- |
| `harnessweaver spec validate [SPEC] [-e ENV]` | Loads the spec with every check the app runs, and prints the layers, tasks and adoption level |
| `harnessweaver spec explain [SPEC] [--path PREFIX]` | Every effective value, the layer it came from, and its locks and bounds |
| `harnessweaver spec diff BEFORE AFTER` | Compares two effective specs (values, locks, level) as Markdown, for PR comments; either side can be `git:<ref>:<path>` |
| `harnessweaver doctor [SPEC]` | Validation plus advice: the next level, reachable hooks, retry owners, pins, shadow guards, content capture |
| `harnessweaver hooks [SPEC] [--task TASK]` | The middleware on every hook point, in run order |

See the [CLI reference](../cli.md).
