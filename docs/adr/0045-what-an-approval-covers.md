# ADR-0045: What an approval covers: one execution, by the role that step needs

**Status:** Accepted. Amends [ADR-0021](0021-resuming-approved-steps.md).

## Decision

**An approval of a tool call covers one execution by default.** `approvals.grant_scope` chooses:

- `call` (the default): the call the human approved runs once. Asking for it again asks a human again.
- `run`: a matching call passes for the rest of the run, as it did before this ADR. Budgets, rate limits and idempotency keys are then the only bound on repeats.

It is a spec-level setting and not a task-level one, so a baseline locks one path to keep it (`locks: [approvals.grant_scope]`). An approved output isn't affected: it matches by content and repeats nothing.

**What "once" means follows how the runner resumes.** A grant is spent as its call starts, whether or not the tool then succeeds.

- A runner that continues from the exact step (`resumable=True`: `direct`, `pydantic_ai.agent`) never repeats a call it finished, so a spent grant is gone for good.
- A runner that runs interrupted work again (`session`, `workflow`) repeats calls it already made, and ADR-0021 promises those don't ask twice. So spent grants stay in the checkpoint, and each pass spends them afresh. `workflow` calls `RunContext.settle_grants()` when a step finishes, because finished steps don't run again.

**An approval counts only if the approver holds the role the step needs.** Governor step 7 now checks the approver against the role a request from it would have named: the manifest's `approval.approver_role`, else the task's `approvals.approver_role`, else the spec's. Without the role, the call asks again, naming that role.

**The new answer replaces the one that wasn't enough.** Any ask that finds the call already holding a grant, from the governor or from middleware, drops that grant, keeping the arguments it chose. So a call that needed two approvals spends them as one, and one that was edited keeps its edit: the second request shows the edited arguments, and approving it approves them.

## Why

ADR-0021 matched approvals by name and arguments so a re-run wouldn't ask twice. Nothing limited the match to that re-run, so one approval let a model repeat a side effect for the rest of the run: an approved payment could be made again without anyone being asked, and untrusted content can steer a model into repeating itself. The docs described the narrow behavior, while DESIGNS.md and a plugin test relied on the wide one. Some apps do want the wide one, for example a repeated low-stakes call a person has cleared once, so it stays available by name, and the safer behavior is what a spec gets without asking.

The role was checked once, in `approve()`, against whichever step asked first, and the grant kept no role. So when a middleware's `Suspend` or a framework's own approval asked first, naming a different role or none, its approver satisfied a manifest's `approver_role` that they didn't hold. That defeats a deterministic gate, and through `edit` lets them choose the arguments too. Checking at step 7 costs one comparison and sits where the rule is already decided.

Asking each role in turn was chosen over making one request name every role. The first asker can't know what the governor will require, since the arguments may yet be edited.

## Consequences

- Behavior changes for existing specs: a repeated identical call now asks again. A spec that relied on the old behavior sets `grant_scope: run`.
- When steps need different roles, a call takes two approvals unless one person holds both.
- A role check moved into a contract: the governor fixtures gain `approved_roles` and `fallback_role`, and TypeScript's governor passes them, though its sessions can't suspend and so never hold an approval at run time (R11).
- A spent grant leaves the checkpoint, so the checkpoint is no longer a list of every approval in the run. The trace and, with `state.record`, the recording still are.
- `workflow`'s settling is run-wide: a parallel step still running when another finishes may ask a human again about a call it repeats. That errs towards asking.
- Running interrupted work again still repeats its side effects, as ADR-0021 says. Use the call's idempotency key.
