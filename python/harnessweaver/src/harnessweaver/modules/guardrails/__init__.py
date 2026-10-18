"""The ``guardrails`` module: built-in guards and the pipeline that runs them (DESIGNS No. 20)."""

from harnessweaver.modules.guardrails.pipeline import (
    STAGE_HOOKS,
    Guard,
    Verdict,
    check,
    guard_handler,
    install_guardrails,
)
from harnessweaver.modules.guardrails.providers import (
    INJECTION_PATTERNS,
    PII_PATTERNS,
    SECRET_PATTERNS,
    InjectionHeuristic,
    LlmJudge,
    PiiRegex,
    RegexDeny,
    SecretsScan,
    SizeLimit,
    TopicDeny,
)

__all__ = [
    "INJECTION_PATTERNS",
    "PII_PATTERNS",
    "SECRET_PATTERNS",
    "STAGE_HOOKS",
    "Guard",
    "InjectionHeuristic",
    "LlmJudge",
    "PiiRegex",
    "RegexDeny",
    "SecretsScan",
    "SizeLimit",
    "TopicDeny",
    "Verdict",
    "check",
    "guard_handler",
    "install_guardrails",
]
