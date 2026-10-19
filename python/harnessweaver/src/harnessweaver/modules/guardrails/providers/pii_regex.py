"""``pii.regex``: find and redact emails, phone numbers, cards, SSNs and IP addresses."""

from typing import Final, Literal

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

__all__ = ["PII_PATTERNS", "PiiRegex"]

type PiiEntity = Literal["EMAIL", "PHONE", "CREDIT_CARD", "SSN", "IP_ADDRESS"]

_OCTET = r"(?:25[0-5]|2[0-4][0-9]|1[0-9][0-9]|[1-9]?[0-9])"

PII_PATTERNS: Final[dict[str, str]] = {
    "EMAIL": r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}",
    "CREDIT_CARD": r"\b(?:[0-9][ -]?){12,18}[0-9]\b",
    "SSN": r"\b[0-9]{3}-[0-9]{2}-[0-9]{4}\b",
    "PHONE": (
        r"(?:\+[0-9]{1,3}[ .-]?)?(?:\([0-9]{3}\)[ .-]?|\b[0-9]{3}[ .-])[0-9]{3}[ .-][0-9]{4}\b"
        r"|\+[0-9]{1,3}(?:[ .-][0-9]{1,4}){2,4}\b"
    ),
    "IP_ADDRESS": rf"\b(?:{_OCTET}\.){{3}}{_OCTET}\b",
}
"""Entity patterns, in the order ties are broken."""


def _luhn(digits: str) -> bool:
    total = 0
    for index, char in enumerate(reversed(digits)):
        value = int(char)
        if index % 2 == 1:
            value = value * 2 - 9 if value > 4 else value * 2
        total += value
    return total % 10 == 0


def _pii_valid(entity: str, text: str) -> bool:
    digits = "".join(c for c in text if c.isdigit())
    if entity == "CREDIT_CARD":
        return 13 <= len(digits) <= 19 and _luhn(digits)
    if entity == "PHONE":
        return 9 <= len(digits) <= 15
    return True


class PiiConfig(GuardConfig):
    entities: list[PiiEntity] = Field(
        default_factory=lambda: list[PiiEntity](
            ["EMAIL", "PHONE", "CREDIT_CARD", "SSN", "IP_ADDRESS"]
        ),
        min_length=1,
    )
    replacement: str = Field(default="[{entity}]", description="'{entity}' is the entity name.")


@provider(
    port="Guardrail",
    name="pii.regex",
    config=PiiConfig,
    deterministic=True,
    latency_class="fast",
    stages=["input", "context", "tool_result", "output", "stream"],
)
class PiiRegex:
    """Finds e-mail addresses, phone numbers, card numbers (Luhn-checked), US SSNs and
    IPv4 addresses, and redacts them as ``[EMAIL]``, ``[PHONE]``, ..."""

    def __init__(self, config: PiiConfig | None = None) -> None:
        config = config or PiiConfig()
        order = list(PII_PATTERNS)
        self.patterns = [
            (entity, compile_pattern(PII_PATTERNS[entity]), order.index(entity))
            for entity in order
            if entity in config.entities
        ]
        self.replacement = config.replacement

    async def check(self, content: str, env: Envelope) -> GuardResult:
        hits = [
            Hit(m.start(), m.end(), entity, self.replacement.format(entity=entity), rank)
            for entity, pattern, rank in self.patterns
            for m in pattern.finditer(content)
            if _pii_valid(entity, m.group())
        ]
        redacted, findings = apply_hits(content, hits)
        return verdict_of(
            GuardAction.REDACT, redacted, findings, f"found {finding_types(findings)}"
        )
