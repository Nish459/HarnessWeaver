# Models and environments

Your code asks for a model by **alias**. The spec says which concrete model each alias means, and an environment overlay can change that without touching code. This chapter adds a second alias, prices and a production overlay.

## Aliases

```yaml title="harness.yaml" hl_lines="12-15 20"
--8<-- "docs_src/tutorial/models/harness.yaml"
```

- `aliases` maps each alias to a model the provider serves. Behind a gateway, that is a model name the gateway knows.
- `default` is the alias used when nothing else names one.
- A task's `model` picks the alias for that task. Here `triage` uses `fast`. A heavier task could use `strong`.

Code, prompts and tests only ever say `fast` or `strong`. Changing which model serves `fast` is a one-line spec change, reviewed like any other.

!!! tip
    An org baseline usually sets `models.allowed_aliases: [fast, strong]` and locks it. A run that asks for another alias is then blocked with `model_not_allowed`. [Profiles and the org baseline](profiles.md) does this.

## Cost

`prices` gives each model's price in US dollars per million tokens. Print what the run used:

```python title="main.py" hl_lines="11-12"
--8<-- "docs_src/tutorial/models/main.py"
```

```console
$ HARNESSWEAVER_ENV=offline uv run python main.py
completed
billing, priority 2: charged twice for the Pro plan, wants one refund.
tokens: 12 in, 18 out
cost: $0.000039
```

The scripted model estimates tokens from the text (one per four characters). A real provider reports them. The cost of a call is found in this order:

1. The cost the provider reports, such as LiteLLM's `x-litellm-response-cost` header, which `openai.chat` reads.
2. The spec's `models.prices`, by the response's model, then the request's model, then the alias.
3. Otherwise the cost is **unknown**. The trace flags it (`cost_source: unknown`), `result.cost_known` is `False`, and nothing is guessed.

There is no built-in price table, because hard-coded prices go stale and mislead.

!!! warning
    A `max_usd` budget can't count what it can't price. If you rely on one, run behind a gateway that reports cost, or give prices.

## Environments

An overlay is a partial spec named `harness.<env>.yaml`, next to `harness.yaml`. `HARNESSWEAVER_ENV=<env>` (or `hw.load(path, env=...)`) merges it over the spec. You already have `offline`. Add one for production:

```yaml title="harness.prod.yaml"
--8<-- "docs_src/tutorial/models/harness.prod.yaml"
```

With `HARNESSWEAVER_ENV=prod`, the app talks to the production gateway and `fast` means `fast-chat-prod`. Everything else in `harness.yaml` stays the same.

| File | Used when | Holds |
| --- | --- | --- |
| `harness.yaml` | Always | What every environment shares |
| `harness.offline.yaml` | `HARNESSWEAVER_ENV=offline` | A scripted model, for tests and demos |
| `harness.prod.yaml` | `HARNESSWEAVER_ENV=prod` | The production gateway, model names, telemetry |

An overlay holds only sections: no `metadata`, no `extends`. A missing overlay file is not an error. [Configuration](../deployment/configuration.md) lists every environment variable.

## What happens on every model call

Every model call goes through the same steps: one made by a runner, by your own code in a session, by an instrumented client, or by an agent framework's adapter.

1. The alias is resolved (the request's, else the task's `model`, else `models.default`) and checked against `models.allowed_aliases`.
2. The budget is checked before the call: call count, tokens and cost so far, and whether the input fits ([Budgets and deadlines](budgets.md)).
3. `model.before` middleware runs, and may change the request. A redaction made here is what the provider receives.
4. The provider is called. When streaming, each chunk fires `stream.chunk`.
5. Usage and cost are recorded (the `harness.budget` note you saw in the trace), and `model.after` middleware runs. A request the model declines is recorded too, then ends the run `blocked` with the code `model_refusal`, before `model.after`.
6. Going over `max_tokens` or `max_usd` after the call blocks the run.

A provider that fails raises a `ProviderError`, code `provider_error`, which is retryable. Retries belong to the gateway, so `openai.chat` makes none of its own (RULES R5).

## Providers

| Provider | From | For |
| --- | --- | --- |
| `scripted` | The core | Tests and offline runs: answers from rules and a list of replies |
| `openai.chat` | `harnessweaver-openai` | Any OpenAI-compatible endpoint: LiteLLM Proxy, OpenAI, vLLM, Ollama |
| `anthropic.messages` | `harnessweaver-anthropic` | Claude, through the Messages API, with its thinking, `effort` and refusal fallbacks |

Each provider's own settings sit next to `provider` in the `models` section. [Providers](../reference/providers.md#models) lists them all, and [Choosing a model provider](../reference/providers.md#choosing-a-model-provider) says what Claude loses through `openai.chat`.

## Recap

- Code asks for **aliases**. The spec maps them to models, and overlays remap them per environment.
- Cost comes from the provider, else from `models.prices`, else it is marked unknown. It is never guessed.
- `harness.<env>.yaml` overlays change a spec per environment, chosen by `HARNESSWEAVER_ENV`.
- Every model call, however it is made, passes the same governed steps.
