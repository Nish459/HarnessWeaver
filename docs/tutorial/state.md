# State and replay

The **state store** keeps what must outlive one call: each run's result, the checkpoints of runs waiting for approval, idempotency records, and, if you ask, recordings of runs that you can replay later against new code. This chapter moves it into a file, approves a run from a second process, and replays it.

## Use a durable store

```yaml title="harness.yaml (the state section)"
--8<-- "docs_src/tutorial/state/harness.yaml:62:65"
```

`sqlite` keeps everything in one file. Its `path` is relative to the working directory. `record: true` also records each run's model answers, tool results and approvals, for replay.

!!! warning
    Recordings hold content: prompts, answers and tool results. They're off by default, they stay in your app's own store, and an org baseline can lock `state.record` off (RULES R9). Add `.harness/state.db` to `.gitignore`.

## Approve after a restart

Start a run that waits for approval, then let the process end:

```python title="main.py"
--8<-- "docs_src/tutorial/state/main.py"
```

In another process, maybe a web handler that an approver's click reaches, load the harness again and approve:

```python title="approve.py"
--8<-- "docs_src/tutorial/state/approve.py"
```

```console
$ HARNESSWEAVER_ENV=offline uv run python main.py
awaiting_approval: run_e7c1838939a447d4bc45a1a4a0a4fe88
$ HARNESSWEAVER_ENV=offline uv run python approve.py run_e7c1838939a447d4bc45a1a4a0a4fe88
completed: Done: the refund is on its way to your card.
```

The second process had nothing in memory. `harness.result(run_id)` read the waiting run from the store, and `approve` resumed it from its checkpoint: the messages so far, the pending call, the budget spent, the run's labels, and where it stopped. While a run waits, its deadline is paused, so the resumed run gets the time it had left.

`async with hw.load(...) as harness:` closes the store when the block ends. Use it, or `await harness.aclose()`, whenever the store holds a file or a connection.

## Replay a run

Replaying runs the task again on the **current** code and spec, with the model's answers, the tool results and the approvals all taken from the recording. Nothing calls out, no tool executes, and no tokens are spent:

```console
$ uv run harnessweaver replay run_e7c1838939a447d4bc45a1a4a0a4fe88 harness.yaml -e offline
same: run run_e7c1838939a447d4bc45a1a4a0a4fe88 (orders) ended completed; the replay ended completed
  output: same
  model answers used: 2 of 2
```

Change a prompt, a rule or a guard, and replay real runs before you ship it: the report says whether each run's status or output changed, which decisions in its trace differ (a guard that fires now, a rule that no longer does), and how many model requests changed. The command exits 1 when the status or output changed, so it can run in CI over a sample of recorded runs. In code, `await harness.replay(run_id)` returns the same `ReplayReport`.

## What the store keeps

| Record | Written when | Read by |
| --- | --- | --- |
| Run results | A run ends or suspends | `harness.result(run_id)` |
| Checkpoints | A run suspends | `approve()`, `resume()` |
| Approval requests and answers | A run suspends; an approver answers | `approve()`, `resume()` |
| Idempotency records | A run with an `idempotency_key` ends | A repeated `harness.run(..., idempotency_key=k)`, which returns the stored result |
| Event log | Status and approval changes | `harness.stream(run_id)` |
| Recordings | `record: true` | `harness.replay(run_id)`, `harnessweaver replay` |
| Online eval samples | `evals.online` grades a run | `harness.samples()`, `harnessweaver eval report` ([Evals](evals.md)) |

| Store | Keeps | Use for |
| --- | --- | --- |
| `memory` | Everything in the process (the default) | Tests, scripts, services that never suspend |
| `sqlite` | Everything in a SQLite file | One process, or a few on one machine, that must survive restarts |

Postgres and Redis stores are *planned* as plugins.

## Idempotency

Pass an `idempotency_key` when a run may be retried, for example by a client whose request timed out:

```python
result = await harness.run("orders", text, principal="ann", idempotency_key=request_id)
```

A second run with the same key, tenant and task returns the stored result instead of running again. Tool calls get a key too, which stays the same when a resumed run repeats a call, so a tool's owner can drop the repeat ([The tool governor](../advanced/governor.md#idempotency)).

## Recap

- `state.use: sqlite` keeps runs, checkpoints and approvals in a file, so a run can be approved after a restart.
- `state.record: true` records runs, and `harnessweaver replay` re-runs them on new code without calling anything.
- `idempotency_key` makes a retried run return the stored result.
