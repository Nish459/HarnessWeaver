# Envelope, labels and budgets

Every hook event travels with the run's **envelope**: who the run acts for, what it is doing, how much it may still spend, and what kind of data has entered it. Middleware reads it to decide; it can't change it.

## The envelope

The envelope is immutable. The mutable state of a run lives in its `RunContext`, which produces a new envelope whenever labels or the remaining budget change.

| Field | Meaning |
| --- | --- |
| `run_id`, `parent_run_id` | This run, and the run that started it |
| `tenant`, `principal` | Who the run acts for. A `Principal` has an `id`, `roles` and `attrs`; a plain string is a principal id with no roles |
| `task`, `task_version` | The task being executed (none in a standalone session without one) |
| `budget` | The remaining budget |
| `deadline` | The absolute deadline, from `budget.deadline` |
| `labels` | What kind of data has entered the run (below) |
| `idempotency_key` | The caller's key for safe retries |
| `trace_id` | Correlates with OpenTelemetry |
| `attributes` | Free-form app tags, such as a channel or region |
| `clock` | The injected clock (`now()`, `is_weekend()`), so time-based rules are testable with a fake clock |

The tenant and principal come from the caller: `harness.run(task, input, principal=user, tenant="acme")`, `harness.session(task, principal=..., tenant=...)`, or the fields of a harnessd request. Policy rules, ACL checks, rate limits, approvals and the memory namespace all key off them.

```python
user = hw.Principal(id="gina", roles=("customer",), attrs={"plan": "pro"})
result = await harness.run("support", question, principal=user, tenant="globex")
```

## Labels and the lethal trifecta

`Labels` record what has entered the run, so later decisions can depend on it:

| Label | Becomes true when |
| --- | --- |
| `untrusted_seen` | Retrieved context, or tool output labelled `untrusted`, enters the run (the default for both) |
| `private_seen` | A tool with `data_access: [pii:*]` runs, or a guard reports a finding marked `private` (as `pii.regex` does for the PII it finds), wherever that guard runs |
| `sources` | Lists where the untrusted and private data came from (context sources, tools, guards) |
| `data_class` | A data classification the app can set |

These drive the **lethal-trifecta check** (RULES S3): untrusted content (which may carry injected instructions), private data, and a tool that can send data out are each harmless alone and dangerous together. A tool with `egress`, called while both labels are set, needs approval (`tools.trifecta: require_approval`, the default) or is blocked (`block`). See [Tools](../advanced/governor.md).

Policy rules can read labels too: `when: "labels.untrusted_seen && tool.name == 'send_email'"`.

## Budgets

A budget limits one run:

| Limit | Meaning |
| --- | --- |
| `max_usd` | Total cost in US dollars |
| `max_tokens` | Input plus output tokens |
| `max_model_calls` | Model calls |
| `max_tool_calls` | Tool calls |
| `deadline` | Wall-clock time for the whole run, as a duration (`30s`, `5m`, `1h30m`) |

They come from three places, and the tightest value of each limit applies:

1. `budgets.per_run` in the spec (often capped by the org baseline's `bounds`).
2. The task's `budget`.
3. A caller's per-run override, `harness.run(..., budget={"max_usd": 0.10})`, allowed only for the fields the task lists in `budget.overridable`, and only downward (RULES R10).

```yaml
budgets:
  per_run: { max_usd: 2.00, deadline: 5m }       # every run
tasks:
  extract:
    budget:
      max_model_calls: 3
      max_usd: 0.05
      deadline: 30s
      overridable: [max_usd, deadline]            # callers may lower these, never raise them
```

### Where budgets are enforced

| Check | Hook | Behavior |
| --- | --- | --- |
| Pre-check of the next model call | `model.before` | Blocks (`budget_exceeded`) when the call count, tokens or cost has reached its limit, or when the request's estimated input (one token per four characters) won't fit in the tokens left. A call is counted when it goes ahead |
| Actual usage and cost | `model.after` | Adds the response's usage and cost; going over `max_tokens` or `max_usd` blocks the run |
| Tool calls | before `tool.before` | Counts the call against `max_tool_calls` |
| Deadline | the whole run | When it expires, the run fails with `DeadlineExceeded` |

Each check, and each call's usage and cost source, is a `harness.budget` trace note (RULES R13). While a run waits for approval its deadline is paused: the resumed run gets the time it had left.

A runner or adapter must reach `model.before` and `model.after` when a model limit is set, and `tool.before` when `max_tool_calls` is set; otherwise the spec fails to load (`UnreachableHook`, R4). This is how an `instrument()`ed client can never run outside its budget.

### Cost

There is no built-in price table, because hard-coded prices go stale and mislead ([ADR-0012](../adr/0012-no-price-table.md)). A call's cost is resolved in this order:

1. The cost the provider reports, such as LiteLLM's `x-litellm-response-cost` header (read by `openai.chat`).
2. The spec's `models.prices`, per model, in USD per million tokens:

    ```yaml
    models:
      prices:
        fast-chat: { input_per_mtok: 0.15, output_per_mtok: 0.60 }
    ```

3. The `genai-prices` package, if installed *(planned)*.
4. Otherwise the cost is **unknown**. That is flagged on the trace (`cost_source: unknown`) and in `RunResult.cost_known`, and never guessed. A `max_usd` limit can't count what it can't price, so run behind a gateway that reports cost, or give prices, when you rely on `max_usd`.

Prices are looked up by the response's model, then the request's model, then its alias.

## Durations

Durations in the spec are strings such as `250ms`, `20s`, `5m`, `1h30m` or `1d2h`, or a plain number of seconds (`20`, `0.25`). The units are `d`, `h`, `m`, `s` and `ms`, lowercase, largest first, each used once, with an optional fraction (`1.5s`). A string needs a unit: `"5"` is an error, while the number `5` is five seconds. Negative values and precision below a millisecond are errors. The same parser runs in Python and TypeScript (fixtures suite `durations`).
