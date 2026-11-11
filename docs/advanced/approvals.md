# Approvals in depth

[Approvals](../tutorial/approvals.md) in the tutorial suspends a run, approves it and resumes it. This page covers what happens underneath: the request, grants, how each runner resumes, crash safety and background runs.

## The request

An `ApprovalRequest` has `approval_id`, `run_id`, `reason`, `approver_role`, the pending `call` and `tool` (for a tool call), `requested_at` and `expires_at`. It is a contract (schema `approval-request`), so a channel can send it anywhere as JSON.

- **Approver role:** from the step that asked (a middleware's `Suspend`, or the manifest's `approval.approver_role`), else the task's `approvals.approver_role`, else `approvals.approver_role`.
- **Expiry:** the task's `approvals.timeout`, else `approvals.timeout` (24 hours from the defaults profile).

`harness.approve` checks that the approver holds the role, fires `approval.resolved` (middleware there can re-check the answer), saves the answer, and only then resumes. Over HTTP the same answer is `POST /v1/runs/{run_id}/approvals/{approval_id}` with `{decision, approver, edited_args, reason}` ([harnessd](sidecar.md)).

```yaml
approvals:
  use: webhook                      # memory (default), callback, console, webhook, email
  url: https://approvals.acme.example/hooks/harness
  headers_env: { Authorization: APPROVALS_TOKEN }
  timeout: 24h
  on_timeout: escalate              # or reject
  approver_role: finance            # when the step that asked names none
tasks:
  refund:
    approvals: { tools: [refund_payment], approver_role: finance, timeout: 4h }
state: { use: sqlite }              # so waiting runs survive a restart
```

Or send approval requests by e-mail, using only the standard library:

```yaml
approvals:
  use: email
  sender: harness@acme.example
  recipients: [finance-approvals@acme.example]
  # host: direct setting (required)
  # login_env, password_env default to HARNESSWEAVER_EMAIL_*
  # set login_env/password_env to null for unauthenticated relays
  # port defaults to 587; starttls defaults to true
  # timeout defaults to 30s
```

The message names the task, the tool (or notes an output approval), the reason and how to answer; it never includes raw content (R9). Credentials come from environment variables (S1). In test mode the channel refuses the network (R14).

## Grants

An approval becomes a **grant** that matches the call by tool name and arguments, or the output by its content. When the resumed run repeats that call, it carries the approval into `tool.before` as `event.approval`, so middleware doesn't ask again (but still sees edited arguments). An approved output carries it into `output.before`, where it answers guards that ask for approval: the guard lets it through and adds a `guard_approved` note naming the guard and the approver (R13).

One approval answers every request for approval at that step, and nothing else. It never turns a block, an escalation or a repair into an allow, redactions still chain, and shadow guards still record. A rejection is never a grant.

`approvals.grant_scope` says how long a tool call's grant lasts:

| `grant_scope` | A repeat of the approved call |
| --- | --- |
| `call` (default) | Asks a human again: the approval covered one execution |
| `run` | Passes for the rest of the run, without asking. Only budgets, rate limits and idempotency keys bound it, so an approved payment can be made again. Lock it in a baseline if that isn't acceptable (`locks: [approvals.grant_scope]`) |

A re-run isn't a repeat: under `call`, a `session` handler or `workflow` step that runs again after an approval passes the calls it already made without asking, once per approval. Their side effects do happen again, so use the call's idempotency key.

### Different roles

An approval counts only if the approver holds the role that step needs: the manifest's `approval.approver_role`, else the task's `approvals.approver_role`, else the spec's. When a middleware asks the help desk first and the manifest needs treasury, the help desk's approval isn't enough. The run suspends again, naming `treasury`, and the call runs once treasury approves. That is two approvals unless one person holds both roles.

If the first approver edited the arguments, the second request shows the edited arguments, and approving it approves them. A call the edit took under the rule's threshold needs no second approval.

### Concurrent answers

One answer wins. If two answers to one request race, from a double submit, a relay's retry or two approvers, even in separate processes on one state file, exactly one resumes the run. The other gets `NotFound` (HTTP 404 from harnessd) and leaves nothing behind, and the run's stored status matches the winner. An answer that arrives while this process is still suspending the run gets `NotFound` too, and can be sent again.

## How runs resume

| Runner | Resumes |
| --- | --- |
| `direct` | From the exact step: the pending tool call runs with the approval |
| `session`, `workflow` | By running the interrupted handler (or workflow step) again. Finished workflow steps don't run again, and the repeated call matches the grant. Work before a suspension point should be safe to repeat (use the call's idempotency key) |
| `pydantic_ai.agent` | From the agent's saved message history, with the deferred call answered; only the call a human approved runs |

A run's deadline is paused while it waits: the resumed run gets the time it had left.

## Where suspension works

Suspension works in harness-driven runs: `harness.run`, `harness.submit` and the runners. In a standalone session, a wrapped agent and TypeScript, a request for approval **escalates** instead, because the app's code can't be resumed later. A framework's own approval (for example a Pydantic AI tool with `requires_approval=True` under the `pydantic_ai.agent` runner) reaches the harness through `RunContext.approval_needed`.

## Crash safety

- `approve()` saves the answer before resuming. If the process dies mid-resume, `harness.resume(run_id)` continues the run.
- `harness.cancel(run_id)` stops a running or waiting run.
- Use the `sqlite` state store (or a durable plugin) in production, so waiting runs survive restarts ([State and replay](../tutorial/state.md)).

## Background runs

Inside `async with harness:`, `harness.submit(task, input, ...)` starts a run in the background and returns its id at once. `harness.stream(run_id)` yields `RunEvent`s: `status` and `approval` events from the state store's event log, plus live `trace` and `chunk` events. An app can push approval requests to people from that stream:

```python
async with harness:
    run_id = await harness.submit("orders", text, principal=user)
    async for event in harness.stream(run_id):
        if event.type == "approval" and event.approval is not None:
            notify_finance(event.approval)      # your code: e-mail, chat, a queue
```

| Method | What it does |
| --- | --- |
| `harness.submit(...)` | Same arguments as `run`; starts the run in the background |
| `harness.stream(run_id)` | Yields the run's events |
| `harness.result(run_id)` | The run's latest `RunResult` |
| `harness.resume(run_id)` | Continues a run whose approval was saved but which didn't finish |
| `harness.cancel(run_id)` | Stops a running or waiting run |
