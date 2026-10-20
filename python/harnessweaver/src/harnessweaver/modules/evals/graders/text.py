"""Graders that read the output's text: ``contains``, ``regex``, ``citation_present``."""

import re
from typing import ClassVar, Final

from pydantic import Field, field_validator

from harnessweaver.core.evals import EvalSample, Grade
from harnessweaver.core.plugins import provider
from harnessweaver.modules.evals.graders.base import GraderConfig, nonempty, texts
from harnessweaver.modules.evals.values import output_text

__all__ = [
    "CITATION_PATTERN",
    "CitationConfig",
    "CitationPresent",
    "Contains",
    "ContainsConfig",
    "Regex",
    "RegexConfig",
]

CITATION_PATTERN: Final = r"\[([A-Za-z0-9_.:#/-]+)\]"
"""A citation, as ``grounded.citations`` reads it: group 1 is the cited id."""


class ContainsConfig(GraderConfig):
    SHORTHAND: ClassVar[str | None] = "text"

    text: str | tuple[str, ...]
    ignore_case: bool = False

    @field_validator("text")
    @classmethod
    def _some_text(cls, value: str | tuple[str, ...]) -> str | tuple[str, ...]:
        return nonempty(value)


@provider(
    port="Evaluator",
    name="contains",
    config=ContainsConfig,
    deterministic=True,
    latency_class="fast",
    sample={"text": "refund"},
)
class Contains:
    """The output's text contains every listed text."""

    def __init__(self, config: ContainsConfig) -> None:
        self.config = config

    async def grade(self, sample: EvalSample) -> Grade:
        text = output_text(sample.output)
        needles = texts(self.config.text)
        if self.config.ignore_case:
            text, needles = text.lower(), tuple(n.lower() for n in needles)
        missing = [str(i + 1) for i, needle in enumerate(needles) if needle not in text]
        if not missing:
            return Grade.of(True)
        return Grade.of(False, f"text {', '.join(missing)} of {len(needles)} not found")


class RegexConfig(GraderConfig):
    SHORTHAND: ClassVar[str | None] = "pattern"

    pattern: str = Field(min_length=1)

    @field_validator("pattern")
    @classmethod
    def _compiles(cls, pattern: str) -> str:
        try:
            re.compile(pattern)
        except re.error as exc:
            raise ValueError(f"invalid pattern: {exc.msg}") from None
        return pattern


@provider(
    port="Evaluator",
    name="regex",
    config=RegexConfig,
    deterministic=True,
    latency_class="fast",
    sample={"pattern": "INV-\\d+"},
)
class Regex:
    """The pattern matches somewhere in the output's text."""

    def __init__(self, config: RegexConfig) -> None:
        self.pattern = re.compile(config.pattern)

    async def grade(self, sample: EvalSample) -> Grade:
        passed = self.pattern.search(output_text(sample.output)) is not None
        return Grade.of(passed, None if passed else "the pattern doesn't match")


class CitationConfig(GraderConfig):
    SHORTHAND: ClassVar[str | None] = "ids"

    ids: str | tuple[str, ...] = Field(default=(), description="Ids that must be cited.")
    pattern: str = Field(default=CITATION_PATTERN, description="Group 1 is the cited id.")

    @field_validator("pattern")
    @classmethod
    def _has_group(cls, pattern: str) -> str:
        try:
            compiled = re.compile(pattern)
        except re.error as exc:
            raise ValueError(f"invalid pattern: {exc.msg}") from None
        if compiled.groups < 1:
            raise ValueError("the pattern needs a group for the cited id")
        return pattern


@provider(
    port="Evaluator",
    name="citation_present",
    config=CitationConfig,
    deterministic=True,
    latency_class="fast",
)
class CitationPresent:
    """The output cites something, or every listed id (``[kb-1]``)."""

    def __init__(self, config: CitationConfig | None = None) -> None:
        self.config = config or CitationConfig()
        self.pattern = re.compile(self.config.pattern)

    async def grade(self, sample: EvalSample) -> Grade:
        cited = {m.group(1) for m in self.pattern.finditer(output_text(sample.output))}
        wanted = texts(self.config.ids)
        if not wanted:
            return Grade.of(bool(cited), None if cited else "nothing is cited")
        missing = [i for i in wanted if i not in cited]
        return Grade.of(not missing, f"{', '.join(missing)} not cited" if missing else None)
