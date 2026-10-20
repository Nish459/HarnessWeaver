"""The middleware that runs one guard, or a parallel group of guards, on a stage."""

from collections.abc import Sequence
from typing import Any

import anyio

from harnessweaver.core.context import current_run
from harnessweaver.core.envelope import Envelope
from harnessweaver.core.guards import GuardAction
from harnessweaver.core.hooks import (
    ContextEvent,
    OutputEvent,
)
from harnessweaver.core.middleware import Handler
from harnessweaver.core.outcomes import Continue, Outcome
from harnessweaver.core.runs import ApprovalDecision
from harnessweaver.modules.guardrails.pipeline.content import content_of
from harnessweaver.modules.guardrails.pipeline.guards import (
    ACTION_RANK,
    Guard,
    Stage,
    Verdict,
    check,
    outcome_of,
    shadow_outcome,
)

__all__ = ["guard_handler"]


async def _member(
    guard: Guard, texts: Sequence[str], env: Envelope, approval: ApprovalDecision | None
) -> Verdict:
    """A parallel group member, with its own timeout and fail mode."""
    try:
        with anyio.fail_after(guard.timeout.total_seconds() if guard.timeout else None):
            return await check(guard, texts, env, approval)
    except Exception as exc:
        reason = f"guard failed ({type(exc).__name__})"
        ctx = current_run()
        if ctx is not None:
            ctx.trace.note(f"guard:{guard.id}", reason, code="guard_error")
        if guard.fail_mode == "open":
            return Verdict(GuardAction.ALLOW, tuple(texts))
        return Verdict(GuardAction.BLOCK, tuple(texts), reason)


async def _group(
    guards: Sequence[Guard],
    texts: Sequence[str],
    env: Envelope,
    approval: ApprovalDecision | None,
) -> tuple[Verdict, list[str]]:
    verdicts: list[Verdict | None] = [None] * len(guards)

    async def run(index: int) -> None:
        verdicts[index] = await _member(guards[index], texts, env, approval)

    async with anyio.create_task_group() as group:
        for index in range(len(guards)):
            group.start_soon(run, index)
    done = [v for v in verdicts if v is not None]
    notes = [
        f"would {v.action.value}: {g.id}"
        for g, v in zip(guards, done, strict=True)
        if g.shadow and v.action not in (GuardAction.ALLOW, GuardAction.LOG_ONLY)
    ]
    notes += [
        f"{g.id}: approved by {v.approved_by}"
        for g, v in zip(guards, done, strict=True)
        if v.approved_by
    ]
    enforced = [(g, v) for g, v in zip(guards, done, strict=True) if not g.shadow]
    worst = Verdict(GuardAction.ALLOW, tuple(texts))
    for _, verdict in enforced:
        if ACTION_RANK[verdict.action] > ACTION_RANK[worst.action]:
            worst = verdict
    if worst.action is GuardAction.REDACT:
        current = list(texts)
        for guard, verdict in enforced:
            if verdict.action is GuardAction.REDACT:
                again = await _member(guard, current, env, approval)
                if again.action is GuardAction.REDACT:
                    current = list(again.texts)
        worst = Verdict(GuardAction.REDACT, tuple(current), worst.reason, worst.findings)
    return worst, notes


def guard_handler(stage: Stage, guards: Sequence[Guard], label: str) -> Handler:
    """The middleware for one guard, or one parallel group of guards."""
    if not guards:
        raise ValueError("a guard handler needs at least one guard")

    async def handle(event: Any, env: Envelope) -> Outcome | None:
        if stage == "context":
            return await _context(event, env, guards, label)
        texts, rebuild = content_of(stage, event)
        if not texts:
            return None
        # Only an output carries a human's approval to the guards (DESIGNS No. 18).
        approval = event.approval if isinstance(event, OutputEvent) else None
        if len(guards) == 1:
            verdict = await check(guards[0], texts, env, approval)
            if guards[0].shadow:
                return shadow_outcome(label, verdict)
            return outcome_of(label, verdict, stage, rebuild(verdict.texts))
        verdict, notes = await _group(guards, texts, env, approval)
        outcome = outcome_of(label, verdict, stage, rebuild(verdict.texts))
        if notes and isinstance(outcome, Continue):
            return Continue(modified=outcome.modified, note="; ".join(notes))
        return outcome

    return handle


async def _context(
    event: ContextEvent, env: Envelope, guards: Sequence[Guard], label: str
) -> Outcome | None:
    kept = []
    dropped = 0
    changed = False
    notes: list[str] = []
    for item in event.items:
        content = item.content
        drop = False
        for guard in guards:
            verdict = await check(guard, [content], env)
            if verdict.action in (GuardAction.ALLOW, GuardAction.LOG_ONLY):
                continue
            if guard.shadow:
                notes.append(f"would {verdict.action.value}: {guard.id}")
                continue
            if verdict.action is GuardAction.REDACT:
                content = verdict.texts[0]
            elif verdict.action in (GuardAction.BLOCK, GuardAction.REPAIR):
                drop = True
                break
            else:
                return outcome_of(label, verdict, "context", None)
        if drop:
            dropped += 1
            continue
        if content != item.content:
            changed = True
            kept.append(item.model_copy(update={"content": content}))
        else:
            kept.append(item)
    if dropped:
        notes.append(f"dropped {dropped} item(s)")
    note = "; ".join(notes) or None
    if dropped or changed:
        return Continue(modified=event.model_copy(update={"items": tuple(kept)}), note=note)
    return Continue(note=note)
