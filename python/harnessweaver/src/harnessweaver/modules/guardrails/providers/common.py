"""What the built-in guards share: config base, pattern hits, redaction and verdicts."""

import re
from collections.abc import Sequence
from dataclasses import dataclass

from pydantic import BaseModel, ConfigDict

from harnessweaver.core.guards import Finding, GuardAction, GuardResult

__all__ = ["GuardConfig", "Hit", "apply_hits", "compile_pattern", "finding_types", "verdict_of"]


class GuardConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


@dataclass(frozen=True, slots=True)
class Hit:
    start: int
    end: int
    type: str
    replacement: str
    order: int


def compile_pattern(pattern: str, ignore_case: bool = False) -> re.Pattern[str]:
    flags = re.ASCII | (re.IGNORECASE if ignore_case else 0)
    return re.compile(pattern, flags)


def apply_hits(
    content: str, hits: Sequence[Hit], *, private: bool = False
) -> tuple[str, tuple[Finding, ...]]:
    """Replace non-overlapping hits: earliest start wins, then the longest, then list order.

    ``private`` marks the findings as private data (S3)."""
    chosen: list[Hit] = []
    for hit in sorted(hits, key=lambda h: (h.start, -(h.end - h.start), h.order)):
        if chosen and hit.start < chosen[-1].end:
            continue
        chosen.append(hit)
    redacted = content
    for hit in reversed(chosen):
        redacted = redacted[: hit.start] + hit.replacement + redacted[hit.end :]
    findings = tuple(
        Finding(type=h.type, start=h.start, end=h.end, private=private) for h in chosen
    )
    return redacted, findings


def verdict_of(
    action: GuardAction, content: str, findings: tuple[Finding, ...], reason: str
) -> GuardResult:
    if not findings:
        return GuardResult.allow()
    return GuardResult(action=action, content=content, findings=findings, reason=reason)


def finding_types(findings: Sequence[Finding]) -> str:
    return ", ".join(sorted({f.type for f in findings}))
