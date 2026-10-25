# Budgets and deadlines

A model that keeps asking for repairs, or an agent that keeps calling tools, costs money and time. A **budget** limits one run: what it may spend, how many calls it may make, and how long it may take. The harness checks it before every call, so a run stops at its limit instead of after it.

## Set limits

```yaml title="harness.yaml" hl_lines="17-18 27-31"
--8<-- "docs_src/tutorial/budgets/harness.yaml"
```

| Limit | Meaning |
| --- | --- |
| `max_usd` | Total cost in US dollars |
| `max_tokens` | Input plus output tokens |
| `max_model_calls` | Model calls, repairs included |
| `max_tool_calls` | Tool calls |
| `deadline` | Wall-clock time for the whole run, such as `30s`, `5m` or `1h30m` |

Limits come from up to three places, and the **tightest** value of each one applies:

1. `budgets.per_run`, for every run of every task. An org baseline usually caps it.
2. The task's `budget`.
3. The caller, for one run, but only for the fields the task lists in `overridable`, and only downward (RULES R10).

## Hit a limit

The offline model from the last chapter needs a repair on every run, so each run makes two model calls. Run once normally, then once with a caller's limit of one call:

```python title="main.py"
--8<-- "docs_src/tutorial/budgets/main.py"
```

```console
$ HARNESSWEAVER_ENV=offline uv run python main.py
completed, cost $0.000155
blocked (budget_exceeded): budget max_model_calls (1) reached
```

The second run was stopped before its repair call: `blocked`, with the code `budget_exceeded`. The repair never reached the model.

A caller can only lower a limit. Asking for more, or overriding a field the task doesn't list, fails before the run starts:

```python
await harness.run("triage", ticket, budget={"max_model_calls": 5})
# BoundViolation: a run may only lower tasks.triage.budget.max_model_calls (R10)
await harness.run("triage", ticket, budget={"deadline": "10s"})
# BoundViolation: tasks.triage.budget.deadline can't be overridden per run; ...
```

## Where budgets are checked

| Check | When | What happens |
| --- | --- | --- |
| The next model call | `model.before` | Blocked when the call count, tokens or cost has reached its limit, or when the request's estimated input won't fit in the tokens left |
| Actual usage and cost | `model.after` | Adds the response's usage and cost. Going over `max_tokens` or `max_usd` blocks the run |
| Tool calls | Before `tool.before` | Counts the call against `max_tool_calls` |
| The deadline | The whole run | When it passes, the run fails with `DeadlineExceeded` |

Each check is a `harness.budget` note in the trace (RULES R13). While a run waits for a person to approve something ([Approvals](approvals.md)), its deadline is paused.

!!! info
    A runner or adapter that can't reach `model.before` and `model.after` can't enforce a model budget. If one is set, the spec fails to load (`UnreachableHook`) rather than run unchecked (RULES R4).

## Durations

Durations are strings such as `250ms`, `20s`, `5m`, `1h30m` or `1d2h`, or a plain number of seconds. The units are `d`, `h`, `m`, `s` and `ms`, largest first, each used once, with an optional fraction (`1.5s`). A string needs a unit: `"5"` is an error, while the number `5` is five seconds.

## Recap

- A budget limits a run's cost, tokens, model calls, tool calls and time. The tightest of the spec's, the task's and the caller's limits applies.
- Callers may only lower the limits a task marks `overridable`.
- Budgets are checked **before** each call, so a run stops at its limit with `budget_exceeded`.
