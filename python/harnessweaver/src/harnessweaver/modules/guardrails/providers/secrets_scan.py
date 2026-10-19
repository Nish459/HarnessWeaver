"""``secrets.scan``: find API keys, tokens and private keys, and block or redact them."""

from typing import Final

from pydantic import Field, field_validator

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

__all__ = ["SECRET_PATTERNS", "SecretsScan"]

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


class SecretsConfig(GuardConfig):
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
            (kind, compile_pattern(pattern, ignore_case), rank)
            for rank, (kind, pattern, ignore_case) in enumerate(SECRET_PATTERNS)
            if config.kinds is None or kind in config.kinds
        ]
        self.replacement = config.replacement

    async def check(self, content: str, env: Envelope) -> GuardResult:
        hits = [
            Hit(m.start(), m.end(), kind, self.replacement, rank)
            for kind, pattern, rank in self.patterns
            for m in pattern.finditer(content)
        ]
        redacted, findings = apply_hits(content, hits)
        return verdict_of(GuardAction.BLOCK, redacted, findings, f"found {finding_types(findings)}")
