# Debugging

When something doesn't do what you expect, HarnessWeaver can tell you why. The spec is checked before anything runs, and every run explains itself. This last chapter shows the tools, on the finished support desk.

## Does the spec load?

`spec validate` loads a spec exactly as `hw.load` does: every layer, lock, bound, plugin, provider and task. A spec that can't run never gets past it:

```console
$ uv run harnessweaver spec validate harness.yaml -e offline
ok: support-desk is valid
  adoption level L3 (required: L1)
  layers: profile://defaults, profile://extraction, org://acme-baseline@1.0.0 (.harness/profiles/acme-baseline.yaml), harness.yaml (harness.yaml), harness.offline.yaml (harness.offline.yaml)
  tasks: answer, orders, triage
```

When it fails, the error names the key, the value and the file. A misspelled key:

```console
$ uv run harnessweaver spec validate harness.yaml -e offline
error: invalid spec:
  tasks.triage.promt: Extra inputs are not permitted (from harness.yaml (harness.yaml))
```

A value outside the baseline's bounds:

```console
$ uv run harnessweaver spec validate harness.yaml -e offline
error: tasks.triage.budget.max_usd = 0.25 (set by harness.yaml (harness.yaml)) is above the maximum 0.1 that org://acme-baseline@1.0.0 (.harness/profiles/acme-baseline.yaml) allows (R10)
```

Unknown keys, providers and hook names always fail, so a typo can never silently switch a control off (RULES R4).

## What could be better?

`doctor` validates the spec, then gives advice:

```console
$ uv run harnessweaver doctor harness.yaml -e offline
OK    level          adoption level L3; risk tier 'internal' requires L1
OK    next level     to reach L4: every task has at least one eval suite
OK    hooks          task answer: runner session reaches every hook it needs
OK    hooks          task orders: runner direct reaches every hook it needs
OK    hooks          task triage: runner direct reaches every hook it needs
OK    retries        retries have one owner
OK    pins           every org and plugin profile is pinned
OK    tools          2 tool manifest(s), all pinned
WARN  shadow guards  guardrails.input[injection] is in shadow mode; promote it to enforce once evals back it (R8)
OK    content        no prompt or output content in telemetry (R9)
```

It tells you what the next [adoption level](../concepts/adoption-levels.md) needs (here, an eval suite for `answer`), and warns about unpinned tools and profiles, duplicate retry owners, guards still in shadow mode, and content capture.

## What runs where, and why is this value set?

`hooks` prints the middleware on each of the 13 hook points, in the order it runs, with its band ([Profiles](profiles.md#see-where-every-value-came-from)). `spec explain` prints each effective value with the layer that set it, and its locks and bounds:

```console
$ uv run harnessweaver spec explain harness.yaml -e offline --path tasks.orders
tasks.orders.runner.use             = "direct"  <- harness.yaml (harness.yaml)
tasks.orders.prompt                 = "orders@2"  <- harness.yaml (harness.yaml)
tasks.orders.output                 = "str"  <- harness.yaml (harness.yaml)
tasks.orders.tools                  = ["lookup_order", "refund_payment"]  <- harness.yaml (harness.yaml)
tasks.orders.budget.max_model_calls = 4  <- harness.yaml (harness.yaml)
tasks.orders.budget.max_tool_calls  = 3  <- harness.yaml (harness.yaml)
tasks.orders.budget.max_usd         = 0.02  <- harness.yaml (harness.yaml)  [max 0.1]
```

`spec diff BEFORE AFTER` compares two effective specs, including locks and the adoption level, as Markdown for a pull request. Either side can be `git:<ref>:<path>`:

```console
$ uv run harnessweaver spec diff git:main:harness.yaml harness.yaml
```

## What happened in this run?

`render_trace(result)` prints the run's trace, as in [Observability](observability.md). When a run doesn't complete, start with its error:

```python
if not result.ok:
    print(result.status.value, result.error.details.get("code"), result.error.message)
```

`details["code"]` names the control that stopped it: `guard_blocked`, `policy_denied`, `budget_exceeded`, `validation_failed`, `approval_rejected`, `trifecta`, `digest_mismatch` and so on. Then find the matching note in the trace. [Troubleshooting](../how-to/troubleshooting.md) lists every load error and block code, with what to do about each.

## Turn on the logs

```python
from loguru import logger

logger.enable("harnessweaver")
```

Logs carry ids and error types, never content, so they are safe to keep on in production.

## Recap

- `spec validate` and `doctor` catch problems before anything runs. `hooks`, `spec explain` and `spec diff` show what the spec really says.
- A run that doesn't complete says why in `result.error.details["code"]`, and its trace shows where.

That's the end of the tutorial. Your support desk is typed, guarded, budgeted, routed, grounded, policy-checked, approved by people where it matters, durable, observable, tested and evaluated, and its own code is still small. The [Advanced User Guide](../advanced/index.md) goes deeper.
