"""Built-in guardrail providers (DESIGNS No. 20, fixtures suite ``guards``).

Each provider finds something in one piece of content and proposes an action.
The spec's ``action`` decides what actually happens (No. 9). Providers that can
redact always return the redacted content, so ``action: redact`` works whatever
their default action is.

The patterns are part of the contract: TypeScript implements the same ones, so
they use only regex syntax both languages share, with ASCII word boundaries.
Findings carry types and positions, never the matched text (R9).
"""

import json
import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Final, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from harnessweaver.core.context import current_run
from harnessweaver.core.envelope import Envelope
from harnessweaver.core.errors import ProviderError
from harnessweaver.core.guards import Finding, GuardAction, GuardResult
from harnessweaver.core.messages import Message, ModelRequest
from harnessweaver.core.plugins import provider

__all__ = [
    "INJECTION_PATTERNS",
    "PII_PATTERNS",
    "SECRET_PATTERNS",
    "InjectionHeuristic",
    "LlmJudge",
    "PiiRegex",
    "RegexDeny",
    "SecretsScan",
    "SizeLimit",
    "TopicDeny",
]


class _Config(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


@dataclass(frozen=True, slots=True)
class _Hit:
    start: int
    end: int
    type: str
    replacement: str
    order: int


def _compile(pattern: str, ignore_case: bool = False) -> re.Pattern[str]:
    flags = re.ASCII | (re.IGNORECASE if ignore_case else 0)
    return re.compile(pattern, flags)


def _apply(content: str, hits: Sequence[_Hit]) -> tuple[str, tuple[Finding, ...]]:
    """Replace non-overlapping hits: earliest start wins, then the longest, then list order."""
    chosen: list[_Hit] = []
    for hit in sorted(hits, key=lambda h: (h.start, -(h.end - h.start), h.order)):
        if chosen and hit.start < chosen[-1].end:
            continue
        chosen.append(hit)
    redacted = content
    for hit in reversed(chosen):
        redacted = redacted[: hit.start] + hit.replacement + redacted[hit.end :]
    findings = tuple(Finding(type=h.type, start=h.start, end=h.end) for h in chosen)
    return redacted, findings


def _verdict(
    action: GuardAction, content: str, findings: tuple[Finding, ...], reason: str
) -> GuardResult:
    if not findings:
        return GuardResult.allow()
    return GuardResult(action=action, content=content, findings=findings, reason=reason)


def _types(findings: Sequence[Finding]) -> str:
    return ", ".join(sorted({f.type for f in findings}))


# --- regex.deny ----------------------------------------------------------------------------------


class RegexDenyConfig(_Config):
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
        self.patterns = [_compile(p, config.ignore_case) for p in config.patterns]
        self.replacement = config.replacement

    async def check(self, content: str, env: Envelope) -> GuardResult:
        hits = [
            _Hit(m.start(), m.end(), f"regex:{index}", self.replacement, index)
            for index, pattern in enumerate(self.patterns)
            for m in pattern.finditer(content)
            if m.end() > m.start()
        ]
        redacted, findings = _apply(content, hits)
        return _verdict(GuardAction.BLOCK, redacted, findings, "matched a denied pattern")


# --- pii.regex -----------------------------------------------------------------------------------

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


class PiiConfig(_Config):
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
            (entity, _compile(PII_PATTERNS[entity]), order.index(entity))
            for entity in order
            if entity in config.entities
        ]
        self.replacement = config.replacement

    async def check(self, content: str, env: Envelope) -> GuardResult:
        hits = [
            _Hit(m.start(), m.end(), entity, self.replacement.format(entity=entity), rank)
            for entity, pattern, rank in self.patterns
            for m in pattern.finditer(content)
            if _pii_valid(entity, m.group())
        ]
        redacted, findings = _apply(content, hits)
        return _verdict(GuardAction.REDACT, redacted, findings, f"found {_types(findings)}")


# --- secrets.scan --------------------------------------------------------------------------------

SECRET_PATTERNS: Final[tuple[tuple[str, str, bool], ...]] = (
    (
        "private_key",
        r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?(?:-----END [A-Z ]*PRIVATE KEY-----|$)",
        False,
    ),
    ("aws_access_key", r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b", False),
    ("github_token", r"\b(?:gh[pousr]_[A-Za-z0-9]{36,}|github_pat_[A-Za-z0-9_]{22,})", False),
    ("slack_token", r"\bxox[abposr]-[A-Za-z0-9-]{10,}", False),
    ("anthropic_key", r"\bsk-ant-[A-Za-z0-9_-]{20,}", False),
    ("openai_key", r"\bsk-(?:proj-|svcacct-)?[A-Za-z0-9_-]{20,}", False),
    ("google_api_key", r"\bAIza[0-9A-Za-z_-]{35}", False),
    ("jwt", r"\beyJ[A-Za-z0-9_-]{8,}\.eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}", False),
    (
        "credential_assignment",
        r"\b(?:password|passwd|pwd|secret|api[_-]?key|access[_-]?token)\s*[:=]\s*[\"']?[^\s\"']{8,}",
        True,
    ),
)
"""``(type, pattern, ignore_case)``, in the order ties are broken."""


class SecretsConfig(_Config):
    kinds: list[str] | None = Field(default=None, description="Only these types; default all.")
    replacement: str = "[SECRET]"

    @field_validator("kinds")
    @classmethod
    def _known(cls, kinds: list[str] | None) -> list[str] | None:
        known = {kind for kind, _, _ in SECRET_PATTERNS}
        unknown = sorted(set(kinds or ()) - known)
        if unknown:
            raise ValueError(f"unknown secret kinds {unknown}; known: {sorted(known)}")
        return kinds


@provider(
    port="Guardrail",
    name="secrets.scan",
    config=SecretsConfig,
    deterministic=True,
    latency_class="fast",
    stages=["input", "context", "tool_result", "output", "stream"],
)
class SecretsScan:
    """Finds credentials: private keys, cloud and API keys, tokens, JWTs, password assignments."""

    def __init__(self, config: SecretsConfig | None = None) -> None:
        config = config or SecretsConfig()
        self.patterns = [
            (kind, _compile(pattern, ignore_case), rank)
            for rank, (kind, pattern, ignore_case) in enumerate(SECRET_PATTERNS)
            if config.kinds is None or kind in config.kinds
        ]
        self.replacement = config.replacement

    async def check(self, content: str, env: Envelope) -> GuardResult:
        hits = [
            _Hit(m.start(), m.end(), kind, self.replacement, rank)
            for kind, pattern, rank in self.patterns
            for m in pattern.finditer(content)
        ]
        redacted, findings = _apply(content, hits)
        return _verdict(GuardAction.BLOCK, redacted, findings, f"found {_types(findings)}")


# --- injection.heuristic -------------------------------------------------------------------------

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


class InjectionConfig(_Config):
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
        self.patterns = [(kind, _compile(p, True), w) for kind, p, w in INJECTION_PATTERNS]

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
            reason=f"possible prompt injection ({_types(findings)})",
        )


# --- size.limit ----------------------------------------------------------------------------------


class SizeConfig(_Config):
    max_chars: int | None = Field(default=None, gt=0)
    max_bytes: int | None = Field(default=None, gt=0, description="UTF-8 bytes.")

    @model_validator(mode="after")
    def _some_limit(self) -> Self:
        if self.max_chars is None and self.max_bytes is None:
            raise ValueError("set max_chars or max_bytes")
        return self


@provider(
    port="Guardrail",
    name="size.limit",
    config=SizeConfig,
    sample={"max_chars": 40},
    deterministic=True,
    latency_class="fast",
    stages=["input", "context", "tool_result", "output", "stream"],
)
class SizeLimit:
    """Flags content over a size; its redaction truncates. Characters are code points."""

    def __init__(self, config: SizeConfig) -> None:
        self.max_chars = config.max_chars
        self.max_bytes = config.max_bytes

    async def check(self, content: str, env: Envelope) -> GuardResult:
        truncated = content if self.max_chars is None else content[: self.max_chars]
        if self.max_bytes is not None:
            while len(truncated.encode("utf-8")) > self.max_bytes:
                truncated = truncated[:-1]
        if truncated == content:
            return GuardResult.allow()
        finding = Finding(type="size", start=len(truncated), end=len(content))
        return GuardResult(
            action=GuardAction.BLOCK,
            content=truncated,
            findings=(finding,),
            reason="content is over the size limit",
        )


# --- topic.deny ----------------------------------------------------------------------------------


class TopicConfig(_Config):
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
            (topic, _compile(r"\b" + re.escape(keyword) + r"\b", True), rank)
            for rank, (topic, keywords) in enumerate(config.topics.items())
            for keyword in keywords
        ]
        self.replacement = config.replacement

    async def check(self, content: str, env: Envelope) -> GuardResult:
        hits = [
            _Hit(m.start(), m.end(), f"topic:{topic}", self.replacement, rank)
            for topic, pattern, rank in self.patterns
            for m in pattern.finditer(content)
        ]
        redacted, findings = _apply(content, hits)
        return _verdict(GuardAction.BLOCK, redacted, findings, f"mentions {_types(findings)}")


# --- llm.judge -----------------------------------------------------------------------------------

_JUDGE_SCHEMA: Final[dict[str, Any]] = {
    "type": "object",
    "properties": {"pass": {"type": "boolean"}, "reason": {"type": "string"}},
    "required": ["pass"],
}


class JudgeConfig(_Config):
    criteria: str = Field(min_length=1, description="What acceptable content looks like.")
    model: str | None = Field(default=None, description="Model alias for the judge.")


@provider(
    port="Guardrail",
    name="llm.judge",
    config=JudgeConfig,
    sample={"criteria": "The content is polite."},
    deterministic=False,
    latency_class="slow",
    stages=["input", "output"],
)
class LlmJudge:
    """Asks a model whether content meets ``criteria``. Probabilistic: it can only make
    things stricter, like every guard (R3). The judge's call is governed and budgeted."""

    def __init__(self, config: JudgeConfig) -> None:
        self.criteria = config.criteria
        self.model = config.model

    async def check(self, content: str, env: Envelope) -> GuardResult:
        ctx = current_run()
        if ctx is None:
            raise ProviderError("llm.judge needs an active run")
        request = ModelRequest(
            alias=self.model,
            messages=(
                Message.system(
                    "You check content against a rule and answer only with JSON "
                    '{"pass": true|false, "reason": "..."}. Rule: ' + self.criteria
                ),
                Message.user(content),
            ),
            output_schema=_JUDGE_SCHEMA,
            temperature=0,
        )
        response = await ctx.generate(request)
        answer: Any = response.output
        if answer is None:
            try:
                answer = json.loads(response.text)
            except json.JSONDecodeError:
                raise ProviderError("llm.judge got an answer that isn't JSON") from None
        if not isinstance(answer, dict) or not isinstance(answer.get("pass"), bool):  # pyright: ignore[reportUnknownMemberType]
            raise ProviderError("llm.judge got an answer without a boolean 'pass'")
        if answer["pass"]:
            return GuardResult.allow()
        # The judge's own explanation may quote the content, so it isn't kept (R9).
        return GuardResult.block("the judge rejected it", findings=(Finding(type="judge"),))
