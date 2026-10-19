"""``llm.judge``: ask a model to judge content. It can only tighten a decision (R3)."""

import json
from typing import Any, Final

from pydantic import Field

from harnessweaver.core.context import current_run
from harnessweaver.core.envelope import Envelope
from harnessweaver.core.errors import ProviderError
from harnessweaver.core.guards import Finding, GuardResult
from harnessweaver.core.messages import Message, ModelRequest
from harnessweaver.core.plugins import provider
from harnessweaver.modules.guardrails.providers.common import GuardConfig

__all__ = ["JudgeConfig", "LlmJudge"]

_JUDGE_SCHEMA: Final[dict[str, Any]] = {
    "type": "object",
    "properties": {"pass": {"type": "boolean"}, "reason": {"type": "string"}},
    "required": ["pass"],
}


class JudgeConfig(GuardConfig):
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
