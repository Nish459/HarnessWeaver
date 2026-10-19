"""Built-in guardrail providers (DESIGNS No. 20, fixtures suite ``guards``).

Each provider finds something in one piece of content and proposes an action.
The spec's ``action`` decides what actually happens (No. 9). Providers that can
redact always return the redacted content, so ``action: redact`` works whatever
their default action is.

The patterns are part of the contract: TypeScript implements the same ones, so
they use only regex syntax both languages share, with ASCII word boundaries.
Findings carry types and positions, never the matched text (R9).
"""

from harnessweaver.modules.guardrails.providers.injection import (
    INJECTION_PATTERNS,
    InjectionHeuristic,
)
from harnessweaver.modules.guardrails.providers.llm_judge import JudgeConfig, LlmJudge
from harnessweaver.modules.guardrails.providers.pii_regex import PII_PATTERNS, PiiRegex
from harnessweaver.modules.guardrails.providers.regex_deny import RegexDeny
from harnessweaver.modules.guardrails.providers.secrets_scan import SECRET_PATTERNS, SecretsScan
from harnessweaver.modules.guardrails.providers.size_limit import SizeLimit
from harnessweaver.modules.guardrails.providers.topic_deny import TopicDeny

__all__ = [
    "INJECTION_PATTERNS",
    "PII_PATTERNS",
    "SECRET_PATTERNS",
    "InjectionHeuristic",
    "JudgeConfig",
    "LlmJudge",
    "PiiRegex",
    "RegexDeny",
    "SecretsScan",
    "SizeLimit",
    "TopicDeny",
]
