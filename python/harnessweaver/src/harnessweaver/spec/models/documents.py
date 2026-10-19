"""The documents: ``Harness`` (an app's effective spec) and ``Profile``."""

from typing import Any, Literal

from pydantic import Field, JsonValue, field_validator

from harnessweaver.spec._raw import as_map
from harnessweaver.spec.models.base import API_VERSION, Level, StrictModel
from harnessweaver.spec.models.sections import (
    ApprovalsSpec,
    BudgetsSpec,
    ContextSourceSpec,
    EvalsSpec,
    GuardrailsSpec,
    Metadata,
    MiddlewareSpec,
    ModelsSpec,
    ObservabilitySpec,
    PluginsSpec,
    PolicySpec,
    PromptsSpec,
    RouterSpec,
    SidecarSpec,
    StateSpec,
    ToolsSpec,
    ValidationSpec,
)
from harnessweaver.spec.models.tasks import TaskSpec

__all__ = ["HarnessSpec", "ProfileSpec", "RequireLevel"]


class RequireLevel(StrictModel):
    default: Level = Level.L0
    tiers: dict[str, Level] = Field(default_factory=dict[str, Level])

    def for_tier(self, tier: str) -> Level:
        return self.tiers.get(tier, self.default)


class Sections(StrictModel):
    plugins: PluginsSpec = PluginsSpec()
    models: ModelsSpec = ModelsSpec()
    routing: dict[str, RouterSpec] = Field(default_factory=dict[str, RouterSpec])
    context: dict[str, ContextSourceSpec] = Field(default_factory=dict[str, ContextSourceSpec])
    guardrails: GuardrailsSpec = GuardrailsSpec()
    validation: ValidationSpec = ValidationSpec()
    tools: ToolsSpec = ToolsSpec()
    policy: PolicySpec = PolicySpec()
    approvals: ApprovalsSpec = ApprovalsSpec()
    budgets: BudgetsSpec = BudgetsSpec()
    state: StateSpec = StateSpec()
    observability: ObservabilitySpec = ObservabilitySpec()
    evals: EvalsSpec = EvalsSpec()
    middleware: tuple[MiddlewareSpec, ...] = ()
    tasks: dict[str, TaskSpec] = Field(default_factory=dict[str, TaskSpec])
    prompts: PromptsSpec = PromptsSpec()
    sidecar: SidecarSpec = SidecarSpec()
    require_level: RequireLevel = Field(
        default=RequireLevel(), description="Set by profiles; the app's level must reach it."
    )

    @field_validator("tools", mode="before")
    @classmethod
    def _manifests_shorthand(cls, value: Any) -> Any:
        mapping = as_map(value)
        if mapping is not None and isinstance(mapping.get("manifests"), str):
            return {**mapping, "manifests": [mapping["manifests"]]}
        return value


class HarnessSpec(Sections):
    """The effective spec of one app, after every layer is merged (DESIGNS No. 11)."""

    api_version: Literal["harnessweaver/v1"] = Field(default=API_VERSION, alias="apiVersion")
    kind: Literal["Harness"] = "Harness"
    metadata: Metadata
    extends: tuple[str, ...] = ()


class ProfileSpec(Sections):
    """A reusable partial spec. The org baseline is a profile with locks and bounds."""

    api_version: Literal["harnessweaver/v1"] = Field(default=API_VERSION, alias="apiVersion")
    kind: Literal["Profile"] = "Profile"
    metadata: Metadata
    extends: tuple[str, ...] = ()
    locks: tuple[str, ...] = Field(default=(), description="Paths later layers can't change (R1).")
    bounds: dict[str, dict[str, JsonValue]] = Field(
        default_factory=dict[str, dict[str, JsonValue]],
        description="`path: {min, max}` limits for numbers and durations (R10).",
    )
