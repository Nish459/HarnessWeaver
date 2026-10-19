"""``grounded.citations``: claims in an answer cite the context the run retrieved (ADR-0032).

An answer cites a context item by its id in square brackets, inside the sentence:
``Refunds take five days [kb-12].`` Sentences end at ``.``, ``!`` or ``?`` followed by
a space, or at a line break; sentences of fewer than ``min_words`` words (titles,
ids) need no citation. The guard flags uncited sentences when fewer than
``min_supported`` of them cite something, and every citation of an id the run
didn't retrieve (a made-up source). Outside a run, or with ``require_known:
false``, any id counts.
"""

import re
from collections.abc import Iterator

from pydantic import Field, field_validator

from harnessweaver.core.context import current_run
from harnessweaver.core.envelope import Envelope
from harnessweaver.core.guards import Finding, GuardAction, GuardResult
from harnessweaver.core.plugins import provider
from harnessweaver.core.text import tokens
from harnessweaver.modules.guardrails.providers.common import GuardConfig

__all__ = ["CitationsConfig", "GroundedCitations"]

_SENTENCE_END = re.compile(r"(?<=[.!?])\s+|\n+")


class CitationsConfig(GuardConfig):
    min_supported: float = Field(default=0.9, ge=0, le=1, description="Share of sentences citing.")
    min_words: int = Field(default=4, ge=1, description="Shorter sentences need no citation.")
    require_known: bool = Field(default=True, description="Citations must name kept context items.")
    pattern: str = Field(default=r"\[([A-Za-z0-9_.:#/-]+)\]", description="Group 1 is the item id.")

    @field_validator("pattern")
    @classmethod
    def _one_group(cls, value: str) -> str:
        if re.compile(value).groups < 1:
            raise ValueError("the pattern needs a group for the cited id")
        return value


def _sentences(text: str) -> Iterator[tuple[int, str]]:
    start = 0
    for found in _SENTENCE_END.finditer(text):
        yield start, text[start : found.start()]
        start = found.end()
    yield start, text[start:]


@provider(
    port="Guardrail",
    name="grounded.citations",
    config=CitationsConfig,
    deterministic=True,
    latency_class="fast",
    stages=["output"],
)
class GroundedCitations:
    """Proposes ``repair`` (the model is asked to cite); set ``action: escalate`` to send
    ungrounded answers to a person instead."""

    def __init__(self, config: CitationsConfig | None = None) -> None:
        self.config = config or CitationsConfig()
        self.pattern = re.compile(self.config.pattern)

    async def check(self, content: str, env: Envelope) -> GuardResult:
        ctx = current_run()
        known = ctx.context_ids if ctx is not None and self.config.require_known else None
        findings: list[Finding] = []
        considered = supported = 0
        for start, sentence in _sentences(content):
            cited = list(self.pattern.finditer(sentence))
            if len(tokens(self.pattern.sub(" ", sentence))) < self.config.min_words:
                continue
            considered += 1
            valid = 0
            for match in cited:
                if known is None or match.group(1) in known:
                    valid += 1
                else:
                    span = (start + match.start(), start + match.end())
                    findings.append(Finding(type="unknown_citation", start=span[0], end=span[1]))
            if valid:
                supported += 1
            else:
                end = start + len(sentence)
                findings.append(Finding(type="uncited_sentence", start=start, end=end))
        if not considered:
            return GuardResult.allow()
        share = supported / considered
        unknown = sum(f.type == "unknown_citation" for f in findings)
        if share >= self.config.min_supported and not unknown:
            return GuardResult.allow()
        reason = f"{supported} of {considered} sentences cite retrieved context"
        if unknown:
            reason += f"; {unknown} citation(s) name nothing the run retrieved"
        return GuardResult(
            action=GuardAction.REPAIR,
            findings=tuple(findings),
            reason=reason,
            score=round(share, 6),
        )
