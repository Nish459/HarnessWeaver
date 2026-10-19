"""``tasks.<name>``: a task's runner, types, prompt, budget and approvals."""

from typing import Any, Literal

from pydantic import Field, field_validator

from harnessweaver.core.durations import Duration
from harnessweaver.core.envelope import Budget
from harnessweaver.spec.models.base import ProviderModel, StrictModel
from harnessweaver.spec.models.sections import GuardrailsSpec

__all__ = ["RunnerSpec", "TaskApprovals", "TaskBudget", "TaskSpec"]


class RunnerSpec(ProviderModel):
    use: str = "direct"


class TaskBudget(StrictModel):
    max_usd: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    max_tokens: int | None = Field(default=None, ge=0)
    max_model_calls: int | None = Field(default=None, ge=0)
    max_tool_calls: int | None = Field(default=None, ge=0)
    deadline: Duration | None = None
    overridable: tuple[
        Literal["max_usd", "max_tokens", "max_model_calls", "max_tool_calls", "deadline"], ...
    ] = Field(default=(), description="Fields a caller may lower for one run (R10).")

    def to_budget(self) -> Budget:
        return Budget(**self.model_dump(exclude={"overridable"}))


class TaskApprovals(StrictModel):
    tools: tuple[str, ...] = ()
    approver_role: str | None = None
    timeout: Duration | None = None
    on_timeout: Literal["escalate", "reject"] | None = None


class TaskSpec(StrictModel):
    version: str = "1.0.0"
    description: str | None = None
    runner: RunnerSpec = RunnerSpec()
    input: str | None = Field(default=None, description="Import path of the input model.")
    output: str | None = Field(
        default=None, description="Import path of the output model, or 'str' for plain text."
    )
    prompt: str | None = Field(default=None, description="Prompt reference, 'name@version'.")
    model: str | None = Field(default=None, description="Model alias for this task.")
    tools: tuple[str, ...] = ()
    budget: TaskBudget = TaskBudget()
    approvals: TaskApprovals | None = None
    guardrails: GuardrailsSpec | None = None

    @field_validator("runner", mode="before")
    @classmethod
    def _runner_shorthand(cls, value: Any) -> Any:
        return {"use": value} if isinstance(value, str) else value
