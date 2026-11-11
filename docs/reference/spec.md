# Section reference

Every section of a `Harness` or `Profile` document, with each field's type, default and meaning. Defaults are what applies when no layer sets the field; the framework's `defaults` profile sets a few of them explicitly (noted below). Unknown keys fail loading, except in blocks that pick a provider, where extra keys are the provider's settings and are validated by the provider.

To start an app spec, a profile or an overlay by picking choices in a form, use the [Spec generator](../learn/spec-generator.md).

Types: *duration* is a string such as `30s`, `5m` or `1h30m`, or a number of seconds ([Durations](../concepts/envelope.md#durations)). *expression* is a [cel-lite](expressions.md) string. *import path* is `package.module:attribute`.

## metadata

Required in every app spec and profile. A profile's metadata describes the profile and is never merged into the app's.

| Field | Type | Default | Meaning |
| --- | --- | --- | --- |
| `name` | string | required | Lowercase letters, digits, `.`, `_` and `-`, starting with a letter or digit |
| `owner` | string | none | The owning team |
| `risk_tier` | string | `internal` | Picks the required adoption level from the baseline's `require_level` |
| `version` | string | none | SemVer; required for org profiles, so `extends` ranges can match it |
| `description` | string | none | Free text |

## extends

A list of profile references, merged before this document: `profile://rag`, `org://acme-baseline@^1`, `profile://acme.baseline@^1`, or a file path. See [Layers](../advanced/layers.md#profiles).

## plugins

| Field | Type | Default | Meaning |
| --- | --- | --- | --- |
| `local` | list of module paths | `[]` | In-repo modules that expose a `plugin` object (`"app.harness_plugin"`), for plugins that aren't installed packages |
| `allow` | list of namespaces | none (any installed plugin) | The plugin namespaces this spec may use; usually set and locked by the org baseline. The core's built-in providers are always allowed |

## models

Picks the model provider. Extra keys are the provider's settings ([Models](../tutorial/models.md)).

| Field | Type | Default | Meaning |
| --- | --- | --- | --- |
| `provider` | name | none | The `ModelProvider`: `openai.chat`, `anthropic.messages`, `scripted`, or a plugin's |
| `default` | alias | none | The alias used when a request names none |
| `aliases` | map of alias to model | `{}` | What each alias means for this provider (`fast: gpt-x-mini`). Overlays remap them per environment |
| `allowed_aliases` | list of aliases | none (any) | The aliases runs may request; others are blocked (`model_not_allowed`). Usually set by the baseline |
| `prices` | map of model to price | `{}` | `{input_per_mtok, output_per_mtok}` in USD per million tokens, used when the provider reports no cost |

```yaml
models:
  provider: openai.chat
  base_url: http://localhost:4000     # openai.chat's own settings
  api_key_env: LITELLM_API_KEY
  default: fast
  aliases: { fast: fast-chat, strong: strong-chat }
  prices:
    fast-chat: { input_per_mtok: 0.15, output_per_mtok: 0.60 }
```

## routing

A map of router name to router ([Routing](../tutorial/routing.md)).

| Field | Type | Default | Meaning |
| --- | --- | --- | --- |
| `options` | list of strings | required (at least one) | The answers this router may give |
| `cascade` | keyed list of stages | `[]` | Stages tried in order; the first confident answer wins |
| `default` | string | none | The answer when no stage is confident; must be one of `options`. Without one, an undecided router abstains |

Each stage:

| Field | Type | Default | Meaning |
| --- | --- | --- | --- |
| `id` | string | `<use>#<n>` | Names the stage in traces and merges |
| `use` | name | required | The `Decider`: `rules`, `lexical`, `semantic`, `llm`, or a plugin's |
| `threshold` | number 0 to 1 | none | The lowest confidence a probabilistic stage's answer needs; without one, any confidence wins |
| *other keys* | | | The stage's settings ([stages](../tutorial/routing.md#stages)) |

## context

A map of source name to context source ([Context and memory](../tutorial/context.md)).

| Field | Type | Default | Meaning |
| --- | --- | --- | --- |
| `use` | name | required | The `ContextProvider`: `memory`, `passthrough`, or a plugin's |
| `label` | `untrusted` or `trusted` | `untrusted` | Whether items from this source count as untrusted (RULES S3) |
| `max_items` | integer > 0 | none | Keep at most this many items |
| `max_tokens` | integer > 0 | none | Keep items while their total size fits (one token per four characters) |
| `require_acl` | boolean | `false` | Also drop items that carry no ACL, not only items whose ACL excludes the run |
| *other keys* | | | The provider's settings (`memory`: `documents` or `file`) |

## memory

The store behind `s.memory`. Entries are namespaced by tenant, principal and task.

| Field | Type | Default | Meaning |
| --- | --- | --- | --- |
| `use` | name | `memory` | The `Memory` provider; `memory` keeps entries in process |
| `default_ttl` | duration | none (no expiry) | When entries expire, unless `put` gives a `ttl` |

## guardrails

Guards per stage. Each stage is a keyed list ([Guardrails](../tutorial/guardrails.md)).

| Stage | Hook point | Checks |
| --- | --- | --- |
| `input` | `input.before` | The run's input, or what `s.guard("input", ...)` passes |
| `context` | `context.after` | Each retrieved item; a block drops the item |
| `tool_result` | `tool.after` | A tool's output |
| `output` | `output.before` | A candidate final output |
| `stream` | `stream.chunk` | Each streamed text chunk |

Each guard:

| Field | Type | Default | Meaning |
| --- | --- | --- | --- |
| `id` | string | `<use>#<n>` | Names the guard (`guardrails.input[<id>]`) in traces, locks and merges |
| `use` | name | required | The `Guardrail` provider |
| `action` | guard action | the provider's | Replaces the provider's proposed action whenever it flags something: `allow`, `redact`, `repair`, `escalate`, `require_approval`, `block`, `log_only` |
| `mode` | `enforce` or `log_only` | `enforce` | `log_only` records what it would have done and changes nothing (shadow mode, RULES R8) |
| `where` | `local` or `sidecar` | `local` | Run the provider in the app, or in harnessd at `sidecar.url` |
| `parallel` | boolean | `false` | Consecutive parallel guards in one band run concurrently |
| `fail_mode` | `closed` or `open` | `closed` | What a raise or timeout becomes; baseline guards must stay `closed` |
| `timeout` | duration | none | How long the provider may take |
| `enabled` | boolean | `true` | `false` switches the guard off (not allowed on a locked guard) |
| *other keys* | | | The provider's settings |

## validation

| Field | Type | Default | Meaning |
| --- | --- | --- | --- |
| `max_repairs` | integer >= 0 | `1` | How many times an invalid output is sent back to the model |
| `on_failure` | `block` or `escalate` | `block` | What happens when the last repair still fails (`validation_failed`) |
| `rules` | keyed list | `[]` | Business rules on the output |

Each rule:

| Field | Type | Default | Meaning |
| --- | --- | --- | --- |
| `id` | string | `rule#<n>` | Names the rule (`validation.rules[<id>]`) |
| `when` | expression | required | Over `output`, `input` and `task`. **True means the output breaks the rule**; an expression that can't be evaluated counts as broken |
| `message` | string | required | Sent to the model with the repair request |

## tools

| Field | Type | Default | Meaning |
| --- | --- | --- | --- |
| `manifests` | list of globs | `[]` | `kind: Tool` files, relative to the spec ([Tool manifests](tool-manifests.md)). A single string is accepted |
| `require_manifest` | boolean | `true` | No tool runs without a manifest (RULES S2) |
| `max_output_bytes` | integer > 0 | `20000` | Cut tool output to this many UTF-8 bytes, unless the manifest says otherwise |
| `trifecta` | `require_approval` or `block` | `require_approval` | A call with egress after untrusted content and private data entered the run (S3) |
| `approval_by_risk` | map of risk to `required` or `none` | `{}` | Risk levels whose calls always need approval: `{high: required, critical: required}` |
| `judge` | provider block | none | A guardrail that also sees each call (`{tool, args}`) and may only tighten the decision (governor step 6) |

## policy

| Field | Type | Default | Meaning |
| --- | --- | --- | --- |
| `use` | name | `cel_lite` | The `PolicyEngine`: `cel_lite`, or `cel.policy` from `harnessweaver-cel`. Must be deterministic (RULES R3) |
| `rules` | keyed list | `[]` | The rules |
| `default_effect` | `allow`, `deny` or `require_approval` | `allow` | The effect for a tool call no rule matches |

Each rule:

| Field | Type | Default | Meaning |
| --- | --- | --- | --- |
| `id` | string | `rule#<n>` | Names the rule in decisions and traces |
| `when` | expression | required | True when the rule applies. For `tool.before`: `principal`, `tenant`, `task`, `tool`, `args`, `labels`. For `run.start`: `principal`, `tenant`, `task`, `labels` |
| `effect` | `allow`, `deny` or `require_approval` | required | What the rule decides |
| `reason` | string | none | Shown in the decision |
| `hook` | `tool.before` or `run.start` | `tool.before` | Where the rule applies. `run.start` rules decide whether a run may start, and only restrict |

See [Policy](../tutorial/policy.md) for how rules combine.

## approvals

The approval channel and the defaults for every approval. Extra keys are the channel's settings ([Approvals](../tutorial/approvals.md)).

| Field | Type | Default | Meaning |
| --- | --- | --- | --- |
| `use` | name | `memory` | The `ApprovalChannel`: `memory`, `callback`, `console`, `webhook`, `email`, or a plugin's |
| `timeout` | duration | none (the defaults profile sets `24h`) | How long a request stays open |
| `on_timeout` | `escalate` or `reject` | `escalate` | What an answer after expiry does to the run |
| `approver_role` | string | none | The role that may approve, when the step that asked names none |
| `grant_scope` | `call` or `run` | `call` | How long a tool call's approval lasts: one execution, or the rest of the run ([Approvals in depth](../advanced/approvals.md#grants)) |

## budgets

| Field | Type | Default | Meaning |
| --- | --- | --- | --- |
| `per_run.max_usd` | number >= 0 | none | Cost limit |
| `per_run.max_tokens` | integer >= 0 | none | Input plus output tokens |
| `per_run.max_model_calls` | integer >= 0 | none | Model calls |
| `per_run.max_tool_calls` | integer >= 0 | none | Tool calls |
| `per_run.deadline` | duration | none | Wall-clock limit for the run |

A task's `budget` tightens these for that task. See [Budgets](../concepts/envelope.md#budgets).

## state

| Field | Type | Default | Meaning |
| --- | --- | --- | --- |
| `use` | name | `memory` | The `StateStore`: `memory` (lost when the process stops) or `sqlite` |
| `record` | boolean | `false` | Record each run's model answers, tool results and approvals, for `harnessweaver replay`. Recordings hold content (RULES R9) |
| *other keys* | | | The store's settings: `sqlite` takes `path` (default `.harness/state.db`, relative to the working directory) |

## observability

| Field | Type | Default | Meaning |
| --- | --- | --- | --- |
| `exporter` | `none`, `console` or `otlp` | `none` | Where `otel.sdk` sends telemetry; needs `configure_sdk: true` |
| `endpoint` | URL | none | The OTLP endpoint, such as `http://otel-collector:4318` |
| `capture_content` | boolean | `false` | Put prompts, outputs and tool arguments, after redaction, on spans (RULES R9). Usually locked off by the baseline |
| `configure_sdk` | boolean | `false` | Let `otel.sdk` (from `harnessweaver-otel`) set up the OpenTelemetry SDK; leave it off when the app configures OpenTelemetry itself |
| `service_name` | string | `metadata.name` | The service name on telemetry |
| *other keys* | | | `otel.sdk`'s settings, such as `export_interval` |

## evals

A map of task name to a list of dataset files, plus the reserved key `online` ([Evals](../tutorial/evals.md)).

```yaml
evals:
  support: [evals/golden.yaml, evals/redteam.yaml]
  online: { sample_rate: 0.05, graders: [{ status: completed }] }
```

| `online` field | Type | Default | Meaning |
| --- | --- | --- | --- |
| `sample_rate` | number 0 to 1 | `0` | The share of production runs graded at `run.end`, picked by a hash of the run id |
| `graders` | list of graders | `[]` | Deterministic graders only; online samples have no `expect` |

## middleware

A keyed list of middleware from plugins ([Middleware](../advanced/middleware.md)).

| Field | Type | Default | Meaning |
| --- | --- | --- | --- |
| `id` | string | `<use>#<n>` | Names the item |
| `use` | name | required | The middleware, as `<namespace>.<name>` |
| `band` | `baseline`, `platform`, `app` or `task` | the layer's band | Only profiles may use `baseline` (RULES S8) |
| `hooks` | list of hook points | the middleware's own | Narrow the hooks it attaches to; it can't attach to hooks it doesn't declare |
| `fail_mode` | `closed` or `open` | the middleware's own | Override the declared fail mode; baseline middleware must be `closed` |
| `timeout` | duration | the middleware's own | Override the declared timeout |
| `enabled` | boolean | `true` | Switch it off |
| *other keys* | | | Settings for a class middleware's `config` model |

## tasks

A map of task name to task.

| Field | Type | Default | Meaning |
| --- | --- | --- | --- |
| `version` | string | `1.0.0` | The task's version, on its runs and traces |
| `description` | string | none | Free text |
| `runner` | name or provider block | `direct` | What executes it: `direct`, `session`, `workflow`, `pydantic_ai.agent`, or a plugin's. A string is short for `{use: <name>}` |
| `input` | import path | none | The Pydantic model the input is validated into |
| `output` | import path, or `str` | none | The type the output is parsed into (`str` for plain text). Required for L1 |
| `prompt` | `name@version` | none | The versioned prompt (`direct` sends it as the system message; `pydantic_ai.agent` uses it as instructions) |
| `model` | alias | `models.default` | The model alias for this task |
| `tools` | list of tool names | `[]` | The tools offered to the model (`direct`, `pydantic_ai.agent`). `direct` blocks a call to any other registered tool (`tool_not_offered`) |
| `budget` | budget | none | Tightens `budgets.per_run`, plus `overridable` (below) |
| `approvals` | task approvals | none | Approval settings for this task (below) |
| `guardrails` | guardrails | none | Guards for this task only, in the `task` band, same shape as the `guardrails` section |

`budget` takes `max_usd`, `max_tokens`, `max_model_calls`, `max_tool_calls`, `deadline` and `overridable`, the list of those fields a caller may lower for one run ([Per-run overrides](../advanced/layers.md#per-run-overrides)).

`approvals`:

| Field | Type | Default | Meaning |
| --- | --- | --- | --- |
| `tools` | list of tool names | `[]` | Tools that always need approval in this task |
| `approver_role` | string | `approvals.approver_role` | Who may approve |
| `timeout` | duration | `approvals.timeout` | How long a request stays open |
| `on_timeout` | `escalate` or `reject` | `approvals.on_timeout` | What expiry does |

### Runner settings

The runner block's other keys are the runner's settings.

| Runner | Setting | Default | Meaning |
| --- | --- | --- | --- |
| `direct` | `max_steps` | `8` | Model calls in the tool loop, not counting repairs. Reaching it blocks the run with `max_steps` |
| `session` | `handler` | required | `package.module:function` called as `await fn(session, input)` |
| `workflow` | `steps` | required | The step graph (below) |
| `workflow` | `output` | the last step | The step whose output is the run's output |
| `pydantic_ai.agent` | `agent` | required | `package.module:attribute` of a Pydantic AI agent |
| `pydantic_ai.agent` | `model` | `harness` | `harness`: the spec's `models` answers; `agent`: the agent's own model, still governed |
| `pydantic_ai.agent` | `deps` | none | `package.module:function` called with `(session, input)` that returns the agent's deps |

A workflow step:

| Field | Type | Default | Meaning |
| --- | --- | --- | --- |
| `id` | string | required | Letters, digits, `_` and `-`, starting with a letter |
| `handler` | import path | required | `async (session, inputs) -> output`; `inputs` holds the run's `input` and the outputs of the steps it needs, by id |
| `needs` | list of step ids | `[]` | Steps that must finish first; steps that are ready together run in parallel |
| `evaluator` | import path | none | `async (session, output) -> True, False or feedback text`; makes the step an evaluator-optimizer loop |
| `max_rounds` | integer 1 to 20 | `3` | How many times the handler may run in the loop |
| `on_reject` | `escalate`, `block` or `accept` | `escalate` | What happens when the evaluator never accepts |

In the loop the handler gets `inputs["feedback"]` and `inputs["round"]`. Finished steps are checkpointed, so after an approval only the interrupted step runs again.

## prompts

| Field | Type | Default | Meaning |
| --- | --- | --- | --- |
| `dir` | path | `prompts` | Where versioned prompts live, relative to the spec |

Prompt files are named `<name>@<version>.md` (or `.txt`), or `<name>.md` without a version. A reference picks a file:

| Reference | Picks |
| --- | --- |
| `support_answer@4.1.0` | Exactly that version |
| `support_answer@4` | The file named `support_answer@4.md`, or else the highest `4.x.y` |
| `support_answer` | The highest version, or the unversioned `support_answer.md` |

Placeholders are `{name}`, filled with `str.format_map` semantics; `{{` and `}}` are literal braces. There is no template language; a missing variable is an error. Render one with `s.prompt("support_answer@4", question=...)`, or name it in a task's `prompt`.

## sidecar

| Field | Type | Default | Meaning |
| --- | --- | --- | --- |
| `url` | URL | none | harnessd, for guards declared `where: sidecar` |
| `token_env` | string | `HARNESSD_TOKEN` | The environment variable holding the bearer token |

## Profiles only

| Field | Type | Default | Meaning |
| --- | --- | --- | --- |
| `require_level` | `{default, tiers}` | `{default: L0}` | The level an app must reach, by `metadata.risk_tier` ([Adoption levels](../concepts/adoption-levels.md#requiring-a-level)) |
| `locks` | list of paths | `[]` | Paths later layers can't change ([Locks](../advanced/layers.md#locks)) |
| `bounds` | map of path to `{min, max}` | `{}` | Limits for numbers and durations ([Bounds](../advanced/layers.md#bounds)) |
