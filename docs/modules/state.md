# State and replay

The state store keeps what a run needs to survive beyond one call: its result, checkpoints for runs waiting for approval, idempotency records, an event log for streaming, recordings for replay, and online eval samples.

```yaml
state:
  use: sqlite
  path: .harness/state.db      # relative to the working directory
  record: false                # true: keep runs for `harnessweaver replay`
```

## Stores

| Store | Keeps | Use for |
| --- | --- | --- |
| `memory` | Everything in the process (the default) | Tests, scripts, stateless services that never suspend |
| `sqlite` | Everything in a SQLite file; `path` defaults to `.harness/state.db`, and `:memory:` keeps it in memory | One process, or a few on one machine, that need runs to survive restarts |

Postgres and Redis stores are *planned* as plugins; any `StateStore` provider works, and the conformance suite checks it with a round-trip contract. Durable runners on Temporal or DBOS are planned too ([ADR-0009](../adr/0009-durability-checkpoints.md)); HarnessWeaver never builds a scheduler of its own.

## What is stored

| Record | Written when | Read by |
| --- | --- | --- |
| Run results | A run ends, or suspends | `harness.result(run_id)`, `GET /v1/runs/{run_id}` |
| Checkpoints | A run suspends: messages so far, the pending call, the budget meter, labels, the context ids it kept, the step | `approve()`, `resume()` |
| Approval requests and answers | A run suspends; an approver answers | `approve()`, `resume()` |
| Idempotency records | A run with an `idempotency_key` ends | A repeated `harness.run(..., idempotency_key=k)` for the same `(tenant, task, k)`, which returns the stored result |
| The event log | Status and approval changes | `harness.stream(run_id)` |
| Recordings | `state.record: true`, during a run | `harness.replay(run_id)`, `harnessweaver replay` |
| Online samples | `evals.online` grades a run at `run.end` | `harness.samples()`, `harnessweaver eval report` |

Release the store's resources with `await harness.aclose()` (or `async with harness:`).

## Recording and replay

With `state.record: true`, each run keeps, in order, every model answer (with the digest of its request), tool result (with the call's digest) and human approval it got, as `RecordedCall`s ([ADR-0035](../adr/0035-record-and-replay.md)).

`harness.replay(run_id)`, or `harnessweaver replay RUN_ID [SPEC]`, runs the task again on a copy of the harness built from the **current** code and spec:

- its model answers from the recording, in order, and never spends tokens;
- its tools return the recorded result of a matching call and **never execute**;
- recorded approvals answer the approvals asked for again;
- its runs stay in memory, so the replay leaves no trace in production state.

The `ReplayReport` compares the two runs: their statuses and outputs, the decisions in the two traces (outcomes other than a plain continue, and coded notes such as `guard_fired`), and how many requests changed or calls the recording didn't have. The command exits 1 when the status or output changed, and 2 when the run can't be replayed.

```bash
uv run harnessweaver replay run_8f2c... harness.yaml --format json
```

Use it to check a spec or prompt change against real production runs before it ships. Recordings hold content (prompts, answers, tool results), so they are off by default, kept only in the app's own store, and an org can lock `state.record` off (RULES R9).

## Durability in practice

- A run waiting for approval survives a restart only with a durable store (`sqlite` or a plugin).
- `harness.resume(run_id)` continues a run whose approval was saved but which didn't finish.
- `harness.submit(...)` and `harness.stream(...)` need `async with harness:` around them, which also closes the store.
