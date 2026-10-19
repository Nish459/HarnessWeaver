"""Stages, guards and verdicts: what one guard decides, and the outcome it becomes."""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import timedelta
from typing import Any, Final, Literal

from harnessweaver.core.context import current_run
from harnessweaver.core.envelope import Envelope
from harnessweaver.core.guards import GuardAction, GuardResult
from harnessweaver.core.hooks import (
    Band,
    HookPoint,
)
from harnessweaver.core.middleware import FailMode
from harnessweaver.core.outcomes import Block, Continue, Escalate, Outcome, Retry, Suspend
from harnessweaver.core.ports import Guardrail
from harnessweaver.spec.merge import LayerKind

__all__ = [
    "ACTION_RANK",
    "LAYER_BANDS",
    "STAGE_HOOKS",
    "Guard",
    "Stage",
    "Verdict",
    "check",
    "outcome_of",
    "shadow_outcome",
]

type Stage = Literal["input", "context", "tool_result", "output", "stream"]

STAGE_HOOKS: Final[dict[Stage, HookPoint]] = {
    "input": HookPoint.INPUT_BEFORE,
    "context": HookPoint.CONTEXT_AFTER,
    "tool_result": HookPoint.TOOL_AFTER,
    "output": HookPoint.OUTPUT_BEFORE,
    "stream": HookPoint.STREAM_CHUNK,
}

ACTION_RANK: Final[dict[GuardAction, int]] = {
    GuardAction.ALLOW: 0,
    GuardAction.LOG_ONLY: 0,
    GuardAction.REDACT: 1,
    GuardAction.REPAIR: 2,
    GuardAction.ESCALATE: 3,
    GuardAction.REQUIRE_APPROVAL: 4,
    GuardAction.BLOCK: 5,
}

LAYER_BANDS: Final[dict[LayerKind, Band]] = {
    LayerKind.ORG: Band.BASELINE,
    LayerKind.DEFAULTS: Band.PLATFORM,
    LayerKind.PROFILE: Band.PLATFORM,
    LayerKind.APP: Band.APP,
    LayerKind.OVERLAY: Band.APP,
}


@dataclass(frozen=True, slots=True)
class Guard:
    """One configured guard."""

    id: str
    provider: Guardrail
    action: GuardAction | None = None
    mode: Literal["enforce", "log_only"] = "enforce"
    fail_mode: FailMode = "closed"
    timeout: timedelta | None = None

    @property
    def shadow(self) -> bool:
        return self.mode == "log_only" or self.action is GuardAction.LOG_ONLY


@dataclass(frozen=True, slots=True)
class Verdict:
    """What one guard decided about a list of texts."""

    action: GuardAction
    texts: tuple[str, ...]
    reason: str | None = None
    findings: tuple[str, ...] = ()


async def check(guard: Guard, texts: Sequence[str], env: Envelope) -> Verdict:
    """Run ``guard`` over every text and combine the answers; the most severe wins."""
    ctx = current_run()
    telemetry = ctx.telemetry if ctx is not None else None
    if telemetry is None:
        return await _check(guard, texts, env)
    with telemetry.guard_span(guard.id, None, guard.mode) as span:
        verdict = await _check(guard, texts, env)
        telemetry.guard_done(span, verdict.action.value, list(verdict.findings))
        return verdict


async def _check(guard: Guard, texts: Sequence[str], env: Envelope) -> Verdict:
    worst = GuardAction.ALLOW
    out = list(texts)
    reason: str | None = None
    found: set[str] = set()
    for index, text in enumerate(texts):
        result = await guard.provider.check(text, env)
        if not isinstance(result, GuardResult):  # pyright: ignore[reportUnnecessaryIsInstance]
            raise TypeError(f"guard {guard.id} returned {type(result).__name__}")
        ctx = current_run()
        if ctx is not None and any(f.private for f in result.findings):
            # A fact about the run, whatever the guard does about it: drives the trifecta (S3).
            ctx.mark_private(f"guard:{guard.id}")
        action = result.action
        if action in (GuardAction.ALLOW, GuardAction.LOG_ONLY):
            continue
        if guard.action is not None and guard.action is not GuardAction.LOG_ONLY:
            action = guard.action
        if action is GuardAction.REDACT:
            if result.content is None:
                action = GuardAction.BLOCK
                reason = reason or f"{result.reason or 'flagged'} (it can't be redacted)"
            else:
                out[index] = result.content
        found.update(f.type for f in result.findings)
        reason = reason or result.reason
        if ACTION_RANK[action] > ACTION_RANK[worst]:
            worst = action
    return Verdict(worst, tuple(out), reason, tuple(sorted(found)))


def outcome_of(label: str, verdict: Verdict, stage: Stage, rebuilt: Any) -> Outcome:
    reason = f"{label}: {verdict.reason or verdict.action.value}"
    match verdict.action:
        case GuardAction.ALLOW | GuardAction.LOG_ONLY:
            return Continue()
        case GuardAction.REDACT:
            return Continue(modified=rebuilt, note=reason)
        case GuardAction.REPAIR if stage == "output":
            return Retry(reason=reason)
        case GuardAction.ESCALATE:
            return Escalate(reason=reason)
        case GuardAction.REQUIRE_APPROVAL:
            return Suspend(reason=reason)
        case _:
            return Block(reason=reason, code="guard_blocked")


def shadow_outcome(label: str, verdict: Verdict) -> Outcome:
    if verdict.action in (GuardAction.ALLOW, GuardAction.LOG_ONLY):
        return Continue()
    return Continue(
        note=f"would {verdict.action.value}: {label}: {verdict.reason or ''}".rstrip(": ")
    )
