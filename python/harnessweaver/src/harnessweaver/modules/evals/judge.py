"""The ``llm_judge`` grader: a model scores the output against a rubric (DESIGNS No. 23)."""

import json
from typing import Any, ClassVar, Final

from pydantic import BaseModel, ConfigDict, Field, JsonValue

from harnessweaver.core.context import current_run
from harnessweaver.core.errors import ProviderError
from harnessweaver.core.evals import EvalSample, Grade
from harnessweaver.core.messages import Message, ModelRequest
from harnessweaver.core.plugins import provider

__all__ = ["JudgeGraderConfig", "LlmJudgeGrader"]

_SCHEMA: Final[dict[str, JsonValue]] = {
    "type": "object",
    "properties": {
        "score": {"type": "number", "minimum": 0, "maximum": 1},
        "reason": {"type": "string"},
    },
    "required": ["score"],
}


class JudgeGraderConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    SHORTHAND: ClassVar[str | None] = "rubric"

    rubric: str = Field(min_length=1, description="What a good output does.")
    model: str | None = Field(default=None, description="Model alias; the default if unset.")
    threshold: float = Field(default=0.5, ge=0, le=1, description="The lowest passing score.")


@provider(
    port="Evaluator",
    name="llm_judge",
    config=JudgeGraderConfig,
    deterministic=False,
    latency_class="slow",
    sample={"rubric": "The answer is polite."},
)
class LlmJudgeGrader:
    """Asks a model to score the output from 0 to 1 against ``rubric``, with the input
    and the case's ``expect`` for reference; it passes at ``threshold``.

    The call is governed and budgeted like any other, so it needs an active run:
    ``Harness.evaluate`` grades inside a session. Scores are the model's own and
    uncalibrated; check a judge against labelled cases before trusting it.
    """

    def __init__(self, config: JudgeGraderConfig) -> None:
        self.config = config

    async def grade(self, sample: EvalSample) -> Grade:
        ctx = current_run()
        if ctx is None:
            raise ProviderError("llm_judge needs an active run")
        system = (
            "You grade the output of an AI system against a rubric. Answer only with JSON "
            '{"score": 0 to 1, "reason": "..."}. Rubric: ' + self.config.rubric
        )
        shown = {"input": sample.input, "output": sample.output, "expected": sample.expect}
        response = await ctx.generate(
            ModelRequest(
                alias=self.config.model,
                messages=(
                    Message.system(system),
                    Message.user(json.dumps(shown, ensure_ascii=False, sort_keys=True)),
                ),
                output_schema=_SCHEMA,
                temperature=0,
            )
        )
        answer: Any = response.output
        if answer is None:
            try:
                answer = json.loads(response.text)
            except json.JSONDecodeError:
                raise ProviderError("llm_judge got an answer that isn't JSON") from None
        score = answer.get("score") if isinstance(answer, dict) else None  # pyright: ignore[reportUnknownMemberType, reportUnknownVariableType]
        if not isinstance(score, int | float) or isinstance(score, bool):
            raise ProviderError("llm_judge got an answer without a numeric score")
        value = round(max(0.0, min(float(score), 1.0)), 6)
        passed = value >= self.config.threshold
        # The judge's own reason may quote the output, so it isn't kept (R9).
        return Grade(
            passed=passed,
            score=value,
            reason=None if passed else f"scored {value} (needs {self.config.threshold})",
        )
