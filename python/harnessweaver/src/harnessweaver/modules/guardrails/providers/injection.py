"""``injection.heuristic``: score phrases that try to override instructions."""

from typing import Final

from pydantic import Field

from harnessweaver.core.envelope import Envelope
from harnessweaver.core.guards import Finding, GuardAction, GuardResult
from harnessweaver.core.plugins import provider
from harnessweaver.modules.guardrails.providers.common import (
    GuardConfig,
    compile_pattern,
    finding_types,
)

__all__ = ["INJECTION_PATTERNS", "InjectionHeuristic"]

INJECTION_PATTERNS: Final[tuple[tuple[str, str, float], ...]] = (
    (
        "ignore_instructions",
        r"\b(?:ignore|disregard|forget|override)\b[^.\n]{0,40}\b(?:previous|prior|above|earlier"
        r"|preceding|all|any|your|the|these|those)\b[^.\n]{0,20}\b(?:instructions?|prompts?|rules"
        r"|directions|guidelines)\b",
        1.0,
    ),
    (
        "reveal_prompt",
        r"\b(?:reveal|show|print|repeat|output|tell me)\b[^.\n]{0,30}\b(?:system prompt"
        r"|hidden (?:prompt|instructions)|your instructions|initial instructions)",
        1.0,
    ),
    (
        "role_override",
        r"\b(?:you are now|from now on,? you are|act as|pretend (?:to be|you are))\b[^.\n]{0,40}"
        r"\b(?:unrestricted|unfiltered|jailbroken|developer mode|DAN"
        r"|no (?:rules|restrictions|limits))",
        1.0,
    ),
    (
        "fake_system",
        r"(?:<\|im_start\|>|<\|system\|>|\[system\]|###\s*system\b|BEGIN SYSTEM PROMPT)",
        0.5,
    ),
    (
        "exfiltrate",
        r"\b(?:send|post|upload|exfiltrate)\b[^.\n]{0,40}\b(?:to|at)\b[^.\n]{0,10}https?://",
        0.5,
    ),
)
"""``(type, pattern, weight)``; matched case-insensitively."""


class InjectionConfig(GuardConfig):
    threshold: float = Field(default=0.5, gt=0, le=1, description="Score that flags content.")


@provider(
    port="Guardrail",
    name="injection.heuristic",
    config=InjectionConfig,
    deterministic=True,
    latency_class="fast",
    stages=["input", "context", "tool_result"],
)
class InjectionHeuristic:
    """Scores phrases typical of prompt injection. Cheap, and easy to evade: pair it with a
    classifier for anything that matters."""

    def __init__(self, config: InjectionConfig | None = None) -> None:
        self.threshold = (config or InjectionConfig()).threshold
        self.patterns = [(kind, compile_pattern(p, True), w) for kind, p, w in INJECTION_PATTERNS]

    async def check(self, content: str, env: Envelope) -> GuardResult:
        findings: list[Finding] = []
        score = 0.0
        for kind, pattern, weight in self.patterns:
            match = pattern.search(content)
            if match:
                findings.append(
                    Finding(
                        type=f"injection:{kind}", start=match.start(), end=match.end(), score=weight
                    )
                )
                score += weight
        score = min(score, 1.0)
        if score < self.threshold:
            return GuardResult.allow()
        return GuardResult(
            action=GuardAction.BLOCK,
            findings=tuple(findings),
            score=score,
            reason=f"possible prompt injection ({finding_types(findings)})",
        )
