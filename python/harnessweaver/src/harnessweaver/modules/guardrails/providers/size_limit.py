"""``size.limit``: block content over a character or line limit."""

from typing import Self

from pydantic import Field, model_validator

from harnessweaver.core.envelope import Envelope
from harnessweaver.core.guards import Finding, GuardAction, GuardResult
from harnessweaver.core.plugins import provider
from harnessweaver.modules.guardrails.providers.common import GuardConfig

__all__ = ["SizeLimit"]


class SizeConfig(GuardConfig):
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
