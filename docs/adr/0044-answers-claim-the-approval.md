# ADR-0044: An answer claims the approval before it resumes the run

**Status:** Accepted

## Decision

`StateStore` gains one method, `claim_approval(checkpoint, approval_id) -> bool`. It replaces the run's checkpoint only if that checkpoint still waits on `approval_id`, atomically, and says whether it did. A store shared between processes makes that atomic across them.

`Harness.approve` claims first, before it records the answer, restores the run or tells telemetry. Whoever gets `False` raises `NotFound`, as for an answer to a request that was already answered, and has left nothing behind. `Harness.cancel` claims a waiting run's approval in the same way: if an answer got there first, it returns the run's current result rather than marking it cancelled.

`approve` also raises `NotFound` while this process is still suspending the run, which can happen when a channel gets an answer back before its `notify` returns. The answer isn't consumed, so it can be sent again.

## Why

Moving a run from `awaiting_approval` to `running` was a read followed by a write, with awaits between them. Two answers to one request, from a double submit, a relay's retry or two approvers, could both read the request as pending. On a shared SQLite file each then resumed the run and executed the approved call, or one rejected while the other's side effect ran, leaving a stored status of `blocked` for a call that happened. Reproduced with two real OS processes on one file.

SQLite and every store worth using can do this in one conditional write, so the rule belongs in the port. A lock around `approve` would cover one process only. Using `claim_idempotency` for it would keep a second record of what the checkpoint already says.

## Consequences

- This is an addition to the `StateStore` port, not to a wire contract, so it stays within `harnessweaver/v1` (V2) and has no TypeScript counterpart: TypeScript answers approvals through harnessd. A third-party store must add the method, and the conformance suite checks it.
- Exactly one of several concurrent answers resumes the run. The others get `NotFound`, which is HTTP 404 on harnessd, so a relay's retry can't tell a lost race from a request that was answered earlier. That is the point: either way, the answer that counted is already in.
- `resume()` and `cancel()` of a run already running in another process are unchanged. The process-local `_active` map only sees this process, so cancelling a run another process is executing still marks it cancelled while that process carries on.
