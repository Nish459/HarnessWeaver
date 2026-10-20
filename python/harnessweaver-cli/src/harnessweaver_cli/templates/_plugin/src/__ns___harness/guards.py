"""``__ns__.banned_words``: a guard that blocks content using a word from a list.

A guard is a ``Guardrail`` provider: it checks one piece of content and returns a
``GuardResult``. The spec decides where it runs (``guardrails.input``,
``output``, ...), what it does when it fires (``action:``) and whether it only
records (``mode: log_only``).
"""

import re

from pydantic import BaseModel, ConfigDict, Field

import harnessweaver as hw

__all__ = ["BannedWords", "BannedWordsConfig"]


class BannedWordsConfig(BaseModel):
    """Settings for ``use: __ns__.banned_words``, written next to ``use:`` in the spec."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    words: list[str] = Field(
        min_length=1, description="Words or phrases to block, matched as whole words in any case."
    )


@hw.provider(
    port="Guardrail",
    name="__ns__.banned_words",
    config=BannedWordsConfig,
    deterministic=True,
    latency_class="fast",
    sample={"words": ["forbidden"]},  # the settings the conformance suite builds it with
)
class BannedWords:
    """Blocks content that uses one of the configured words."""

    def __init__(self, config: BannedWordsConfig) -> None:
        # One pattern for every word: whole words only, so "class" doesn't match "classic".
        alternatives = "|".join(re.escape(word) for word in config.words)
        self._pattern = re.compile(rf"\b(?:{alternatives})\b", re.IGNORECASE)

    async def check(self, content: str, env: hw.Envelope) -> hw.GuardResult:
        """Block when a banned word appears. The reason never quotes the content (R9)."""
        if self._pattern.search(content) is None:
            return hw.GuardResult.allow()
        return hw.GuardResult.block("uses a banned word")
