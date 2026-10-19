"""``topic.deny``: block content that mentions a denied topic's keywords."""

import re

from pydantic import Field

from harnessweaver.core.envelope import Envelope
from harnessweaver.core.guards import GuardAction, GuardResult
from harnessweaver.core.plugins import provider
from harnessweaver.modules.guardrails.providers.common import (
    GuardConfig,
    Hit,
    apply_hits,
    compile_pattern,
    finding_types,
    verdict_of,
)

__all__ = ["TopicDeny"]


class TopicConfig(GuardConfig):
    topics: dict[str, list[str]] = Field(min_length=1, description="Topic name -> keywords.")
    replacement: str = "[REDACTED]"


@provider(
    port="Guardrail",
    name="topic.deny",
    config=TopicConfig,
    sample={"topics": {"medical": ["diagnosis"]}},
    deterministic=True,
    latency_class="fast",
    stages=["input", "output"],
)
class TopicDeny:
    """Flags content that mentions denied topics, by whole-word keywords (case-insensitive)."""

    def __init__(self, config: TopicConfig) -> None:
        self.patterns = [
            (topic, compile_pattern(r"\b" + re.escape(keyword) + r"\b", True), rank)
            for rank, (topic, keywords) in enumerate(config.topics.items())
            for keyword in keywords
        ]
        self.replacement = config.replacement

    async def check(self, content: str, env: Envelope) -> GuardResult:
        hits = [
            Hit(m.start(), m.end(), f"topic:{topic}", self.replacement, rank)
            for topic, pattern, rank in self.patterns
            for m in pattern.finditer(content)
        ]
        redacted, findings = apply_hits(content, hits)
        return verdict_of(
            GuardAction.BLOCK, redacted, findings, f"mentions {finding_types(findings)}"
        )
