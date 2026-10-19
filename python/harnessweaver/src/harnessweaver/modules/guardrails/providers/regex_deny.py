"""``regex.deny``: block content that matches any of the given patterns."""

import re

from pydantic import Field, field_validator

from harnessweaver.core.envelope import Envelope
from harnessweaver.core.guards import GuardAction, GuardResult
from harnessweaver.core.plugins import provider
from harnessweaver.modules.guardrails.providers.common import (
    GuardConfig,
    Hit,
    apply_hits,
    compile_pattern,
    verdict_of,
)

__all__ = ["RegexDeny"]


class RegexDenyConfig(GuardConfig):
    patterns: list[str] = Field(min_length=1)
    ignore_case: bool = False
    replacement: str = "[REDACTED]"

    @field_validator("patterns")
    @classmethod
    def _compiles(cls, patterns: list[str]) -> list[str]:
        for pattern in patterns:
            try:
                re.compile(pattern)
            except re.error as exc:
                raise ValueError(f"invalid pattern {pattern!r}: {exc}") from None
        return patterns


@provider(
    port="Guardrail",
    name="regex.deny",
    config=RegexDenyConfig,
    sample={"patterns": ["internal-[0-9]+"]},
    deterministic=True,
    latency_class="fast",
    stages=["input", "context", "tool_result", "output", "stream"],
)
class RegexDeny:
    """Blocks content matching any of the configured patterns."""

    def __init__(self, config: RegexDenyConfig) -> None:
        self.patterns = [compile_pattern(p, config.ignore_case) for p in config.patterns]
        self.replacement = config.replacement

    async def check(self, content: str, env: Envelope) -> GuardResult:
        hits = [
            Hit(m.start(), m.end(), f"regex:{index}", self.replacement, index)
            for index, pattern in enumerate(self.patterns)
            for m in pattern.finditer(content)
            if m.end() > m.start()
        ]
        redacted, findings = apply_hits(content, hits)
        return verdict_of(GuardAction.BLOCK, redacted, findings, "matched a denied pattern")
