# Troubleshooting

Most problems surface when a spec loads, never in the middle of a run (RULES R4): `harnessweaver spec validate` and `harnessweaver doctor` show the same errors the app would raise. Every error is a taxonomy error with a stable code ([Outcomes and errors](../concepts/outcomes.md#the-error-taxonomy)). The messages below are real ones.

## When a spec doesn't load

### LockViolation

```text
LockViolation: observability.capture_content is locked by org://acme-baseline@1.1.0 (.../acme-baseline.yaml)
(lock 'observability.capture_content'); it can't be changed (R1)
```

A later layer (your spec or an overlay) changes a path an org profile locked. Remove the change, or restate the same value. If the org's value is wrong for you, the fix is a change to the baseline, by its owners. `harnessweaver spec explain --path <path>` shows the lock and the layer that set it. Remember an overlay can trigger this even when the base spec doesn't: validate every `-e` you deploy.

### BoundViolation

```text
BoundViolation: budgets.per_run.max_usd = 8.0 (set by harness.yaml) is above the maximum 5 that
org://acme-baseline@1.1.0 (.../acme-baseline.yaml) allows (R10)
```

A number or duration is outside a profile's `bounds`. Nothing is clamped, so lower the value. Task budgets are also checked against the `budgets.per_run` bounds. The same error comes from a per-run override that raises a limit, or overrides a field the task doesn't list in `budget.overridable`.

### LevelTooLow

```text
LevelTooLow: app reaches L1 but its risk tier 'customer_facing' requires L2.
Missing: policy.rules has at least one rule
```

The baseline requires a higher adoption level for your `metadata.risk_tier`. Add what the message lists; `harnessweaver doctor` shows the same under `next level`. See [Adoption levels](../concepts/adoption-levels.md).

### UnknownProvider

```text
UnknownProvider: no installed plugin provides namespace 'nope'; install one that does,
or list an in-repo module under plugins.local
UnknownProvider: no Guardrail provider named 'pii.regexx' in plugin 'harnessweaver'; it provides:
grounded.citations, injection.heuristic, llm.judge, pii.regex, regex.deny, secrets.scan, size.limit, topic.deny
```

A `use:` names something that isn't installed, or is misspelled. Install the plugin package (`uv add ...`) or add the module to `plugins.local`; `harnessweaver plugin list` shows what is installed. In TypeScript, a provider that exists only in Python fails the same way: pass the plugin to `load({ plugins })`, use a TypeScript provider, or declare the guard `where: sidecar`.

### PluginNotAllowed

```text
PluginNotAllowed: plugin namespace 'nope' isn't in plugins.allow (acme, anthropic, openai, otel, pydantic_ai)
```

The org baseline's `plugins.allow` doesn't list the namespace. Ask the baseline's owners to review and allow the plugin.

### PluginConflict and IncompatibleContract

Two installed packages claim the same namespace, or a plugin was built for a contract range this core doesn't support. `harnessweaver plugin list` shows each plugin's namespace, version, contract range and compatibility; uninstall one of the conflicting packages, or upgrade the plugin.

### UnreachableHook

A runner or adapter can't reach a hook point the baseline or the budget needs: for example a budget with model limits and an adapter that can't see model calls. Choose a runner or adapter that reaches it (`harnessweaver doctor` lists each task's runner and its hooks), or move the control.

### Other SpecErrors

| Message | Cause | Fix |
| --- | --- | --- |
| `unknown or misplaced key(s) guardrail for a Harness document (allowed: ...)` | A misspelled or misplaced top-level key | Use one of the listed keys |
| `provider pii.regex settings: entitys: Extra inputs are not permitted` | A misspelled provider setting | Check the provider's settings in its module page |
| `guard topic.deny can't run at stage 'context'; it supports input, output` | A guard at a stage its provider doesn't support | Move it, or pick another provider |
| `policy.rules[rule#1].when: unexpected 'end of expression' at position 13` | A cel-lite expression that doesn't compile | Fix the expression ([cel-lite](../reference/expressions.md)); `rule#1` is the generated id of the first rule without one |
| `invalid YAML: duplicate key 'models'` | A key repeated in one map (YAML 1.2 rule) | Merge the two entries |
| `routing.r: default 'b' is not one of the options` | A router's `default` outside its `options` | Add it to `options` or change it |
| `can't find profile 'org://missing@^1'; see HARNESSWEAVER_PROFILE_PATH` | An org profile not on the search path, or no version matching the range | Set `HARNESSWEAVER_PROFILE_PATH` or `--profile-dir`; check the file name (`<name>.yaml` or `<name>@<version>.yaml`) and `metadata.version` |
| `profiles extend each other in a cycle` | Two profiles extending each other | Break the cycle |
| `tools.manifests: no file matches 'tools/*.tool.yaml' under ...` | A manifest glob that matches nothing | Check the path, relative to the spec |
| `a code tool must name a sandbox, such as monty (S4)` | A `transport: code` manifest without `sandbox` | Add `sandbox: monty` (and install `harnessweaver-monty`) |
| `observability.exporter: otlp needs observability.configure_sdk: true; ...` | `observability.exporter` set while `configure_sdk` is false | Set `configure_sdk: true` (with `harnessweaver-otel`), or configure OpenTelemetry in the app and drop `exporter` |

## When a run is blocked

The run's `RunResult.error.details.code` (or the `RunBlocked` error's `details["code"]` in a session) says which control stopped it; the trace says why.

| Code | Means | Look at |
| --- | --- | --- |
| `policy_denied` | A deny rule matched (at `run.start` or governor step 3) | The `harness.policy` or `harness.governor` note names the rule |
| `budget_exceeded` | A limit was reached; `details.limit` names it | The `harness.budget` notes; raise the task's budget within bounds, or reduce calls |
| `deadline_exceeded` | The run's deadline passed | The deadline in the task budget and `budgets.per_run` |
| `guard_blocked` | A guard blocked | The `harness.guard` note names the guard and its finding types; consider shadow mode while tuning |
| `validation_failed` | The output was still invalid after the last repair | The `repair` notes list the problems; improve the prompt or output type, or raise `max_repairs` |
| `retry_exhausted` | `model.after` asked for a second retry | The middleware returning `Retry` |
| `model_not_allowed` | The alias isn't in `models.allowed_aliases` | Use an allowed alias |
| `max_steps` | The `direct` runner's tool loop ran out of model calls | `runner: { use: direct, max_steps: ... }` |
| `tool_unknown`, `manifest_required` | A tool with no registration or manifest | `tools.manifests`, or the tools given in code |
| `tool_not_offered` | The model of a `direct` task called a registered tool the task doesn't offer | Add it to the task's `tools` if the task should have it; otherwise look for what steered the model |
| `digest_mismatch` | A tool's definition changed since its digest was pinned | Review the change, then `harnessweaver tools pin` |
| `schema_invalid` | The arguments don't match the tool's `input_schema` | The note names the failing locations |
| `trifecta` | A tool with egress after untrusted and private data entered the run, with `trifecta: block` | The run's labels and sources; whether the tool needs egress |
| `rate_limited` | The manifest's `rate_limit` was reached | The limit, or the caller's behavior |
| `approval_rejected` | A human rejected the call | - |
| `middleware_error`, `middleware_timeout` | A closed middleware raised or timed out | The `failure` trace event names the middleware and the exception type |
| `retry_not_supported` | A `Retry` where it isn't honored | Return `Block` or `Escalate` there instead |

## When a run fails

A run that ends `failed` never got an answer to check. `RunResult.error` says why: its `code` (`provider_error` when the model couldn't be called) and its `message`, which names the provider and the error type, never what was sent (RULES R9). This is the usual first stumble when moving from the offline overlay to a real model.

| `error.message` | Means | Fix |
| --- | --- | --- |
| `openai.chat needs $LITELLM_API_KEY`, or another variable | The variable that `models.api_key_env` names isn't set | Export it. Running offline needs no key: `HARNESSWEAVER_ENV=offline` |
| `openai.chat: APIConnectionError` | Nothing answered at `models.base_url`: the gateway, or Ollama, isn't running there | Start it, correct `base_url`, or call a provider directly ([Quickstart](../learn/quickstart.md#9-call-a-real-model)) |
| `openai.chat: AuthenticationError (HTTP 401)` | The endpoint refused the key | The key in that variable, and that it belongs to that endpoint |
| `openai.chat: NotFoundError (HTTP 404)` | The endpoint doesn't serve the model an alias maps to, or `base_url` lacks its `/v1` | Map the alias in `models.aliases` to a model id the endpoint serves |
| `openai.chat: RateLimitError (HTTP 429)` | The provider is limiting your requests | A gateway, which retries and falls back, or `max_retries` when calling a provider directly |
| `anthropic.messages needs $ANTHROPIC_API_KEY` | The variable that `models.api_key_env` names isn't set | Export it |
| `anthropic.messages found no credentials: ...` (from older versions of the plugin, `the model provider failed (TypeError)`) | With no `api_key_env`, the Anthropic SDK found no key, no token and no `ant auth login` profile | Set `ANTHROPIC_API_KEY`, run `ant auth login`, or name the key's variable with `models.api_key_env` |
| `anthropic.messages: Config file not found at ...`, or another file or variable | `ANTHROPIC_PROFILE`, `ANTHROPIC_CONFIG_DIR` or the workload identity variables point at credentials that can't be loaded | The message names the file or variable to fix |
| `openai.chat can't call out in test mode (R14)` | Test mode is on, as it is under `harnessweaver test` | Expected in tests: use the offline overlay or a scripted model ([Testing](../tutorial/testing.md)) |

`anthropic.messages` reports connection, key, model and rate-limit errors the same way, under its own name. A `provider_error` is retryable: behind a gateway the gateway retries, and a provider called directly is retried by its SDK up to `max_retries` times.

## Other surprises

| Symptom | Cause | Fix |
| --- | --- | --- |
| `harnessweaver: command not found` | The CLI is installed in your project's environment, not on your `PATH` | `uv run harnessweaver ...` inside the project; outside one, `uvx --from harnessweaver-cli harnessweaver ...` |
| `uvx` says the current Python version doesn't satisfy `Python>=3.12` | Your default Python is older than 3.12 | `uvx --python 3.12 --from harnessweaver-cli harnessweaver ...`. Inside a project, `uv sync` finds a suitable Python on its own |
| `ProviderError` from every model call in tests | Test mode: live providers refuse to call out | Use a scripted model or a cassette ([Testing](../tutorial/testing.md)) |
| `RunResult.cost_known` is false; `max_usd` never trips | No cost report and no price for the model | Run behind a gateway that reports cost, or add `models.prices` |
| No spans in your backend | No OpenTelemetry SDK is configured | Configure it in the app, or `observability.configure_sdk: true` with `harnessweaver-otel` and an `endpoint` |
| No logs at all | HarnessWeaver is silent by default | `logger.enable("harnessweaver")` |
| A `Suspend` became `escalated` | A standalone session, a wrapped agent or TypeScript can't wait for a person | Run the work as a task (`harness.run`) when it needs approvals |
| An instrumented client raises on `stream=True` | Streaming through `instrument()` is planned | Use the non-streaming call, or `s.generate(stream=True)` in a session |
| A guard fires on content it shouldn't | Guards are blunt instruments | Put it in shadow mode, collect evidence with `eval run`, tune its settings or its `action` |
| harnessd answers 401 | A missing or wrong `Authorization: Bearer` token | The client's token and harnessd's `--token-env` |
| harnessd won't start | No token in `HARNESSD_TOKEN` (or the `--token-env` variable), or a spec that doesn't load | Set the token; run `spec validate` on the same spec and overlay |

When in doubt, run `uv run harnessweaver doctor harness.yaml -e <env>` and read the trace (`harnessweaver.testing.render_trace(result)`).
