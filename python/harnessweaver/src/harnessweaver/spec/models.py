"""The ``harness.yaml`` contract: the effective spec of one app (DESIGNS No. 11).

Sections that pick a provider with ``use:`` accept extra keys: those are the
provider's own settings, validated against the provider's config model when
the harness loads (still R4). Every other model rejects unknown keys.
"""

from enum import StrEnum
from typing import Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, JsonValue, field_validator, model_validator

from harnessweaver.core.decisions import PolicyEffect
from harnessweaver.core.durations import Duration
from harnessweaver.core.envelope import Budget
from harnessweaver.core.guards import GuardAction
from harnessweaver.core.hooks import Band, HookPoint
from harnessweaver.spec._raw import as_map

__all__ = [
    "API_VERSION",
    "ApprovalsSpec",
    "BudgetsSpec",
    "ContextSourceSpec",
    "EvalsSpec",
    "GuardSpec",
    "GuardrailsSpec",
    "HarnessSpec",
    "Level",
    "Metadata",
    "MiddlewareSpec",
    "ModelsSpec",
    "ObservabilitySpec",
    "OnlineEvalsSpec",
    "PluginsSpec",
    "PolicyRule",
    "PolicySpec",
    "Price",
    "ProfileSpec",
    "PromptsSpec",
    "RequireLevel",
    "RouterSpec",
    "RoutingStage",
    "RunnerSpec",
    "SidecarSpec",
    "StateSpec",
    "TaskApprovals",
    "TaskBudget",
    "TaskSpec",
    "ToolsSpec",
    "ValidationRule",
    "ValidationSpec",
]

API_VERSION = "harnessweaver/v1"


class Level(StrEnum):
    """Adoption levels (DESIGNS No. 11)."""

    L0 = "L0"
    L1 = "L1"
    L2 = "L2"
    L3 = "L3"
    L4 = "L4"

    @property
    def rank(self) -> int:
        return int(self.value[1])


class _Strict(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", populate_by_name=True)


class _Provider(BaseModel):
    """A block that selects a provider. Extra keys are that provider's settings."""

    model_config = ConfigDict(frozen=True, extra="allow", populate_by_name=True)

    def provider_settings(self) -> dict[str, Any]:
        """The keys that belong to the provider rather than to HarnessWeaver."""
        return dict(self.model_extra or {})


# --- metadata and plugins -----------------------------------------------------------------


class Metadata(_Strict):
    name: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]*$")
    owner: str | None = None
    risk_tier: str = Field(default="internal", description="Picks the required level.")
    version: str | None = Field(default=None, description="SemVer; required for org profiles.")
    description: str | None = None


class PluginsSpec(_Strict):
    local: tuple[str, ...] = Field(default=(), description="In-repo modules exposing `plugin`.")
    allow: tuple[str, ...] | None = Field(
        default=None, description="Plugin namespaces apps may use; usually locked by the org."
    )


# --- models -------------------------------------------------------------------------------


class Price(_Strict):
    input_per_mtok: float = Field(ge=0, description="USD per million input tokens.")
    output_per_mtok: float = Field(ge=0, description="USD per million output tokens.")


class ModelsSpec(_Provider):
    provider: str | None = Field(default=None, description="e.g. 'openai.chat', 'scripted'.")
    default: str | None = Field(default=None, description="Default model alias.")
    aliases: dict[str, str] = Field(default_factory=dict[str, str])
    allowed_aliases: tuple[str, ...] | None = None
    prices: dict[str, Price] = Field(default_factory=dict[str, Price])


# --- routing ------------------------------------------------------------------------------


class RoutingStage(_Provider):
    id: str | None = None
    use: str
    threshold: float | None = Field(default=None, ge=0, le=1)


class RouterSpec(_Strict):
    options: tuple[str, ...] = Field(min_length=1)
    cascade: tuple[RoutingStage, ...] = ()
    default: str | None = None

    @model_validator(mode="after")
    def _default_is_an_option(self) -> Self:
        if self.default is not None and self.default not in self.options:
            raise ValueError(f"default {self.default!r} is not one of the options")
        return self


# --- context ------------------------------------------------------------------------------


class ContextSourceSpec(_Provider):
    use: str
    label: Literal["untrusted", "trusted"] = "untrusted"
    max_items: int | None = Field(default=None, gt=0)
    max_tokens: int | None = Field(default=None, gt=0)


# --- guardrails and validation ------------------------------------------------------------


class GuardSpec(_Provider):
    id: str | None = None
    use: str
    action: GuardAction | None = Field(default=None, description="Overrides the provider's.")
    mode: Literal["enforce", "log_only"] = Field(
        default="enforce", description="New guards should start as log_only (R8, ADR-0008)."
    )
    where: Literal["local", "sidecar"] = "local"
    parallel: bool = False
    fail_mode: Literal["closed", "open"] = "closed"
    timeout: Duration | None = None
    enabled: bool = True


class GuardrailsSpec(_Strict):
    input: tuple[GuardSpec, ...] = ()
    context: tuple[GuardSpec, ...] = ()
    tool_result: tuple[GuardSpec, ...] = ()
    output: tuple[GuardSpec, ...] = ()
    stream: tuple[GuardSpec, ...] = ()

    def all(self) -> tuple[GuardSpec, ...]:
        return self.input + self.context + self.tool_result + self.output + self.stream


class ValidationRule(_Strict):
    id: str | None = None
    when: str = Field(description="cel-lite predicate over `output`, `input` and `task`.")
    message: str


class ValidationSpec(_Strict):
    max_repairs: int = Field(default=1, ge=0)
    on_failure: Literal["escalate", "block"] = "block"
    rules: tuple[ValidationRule, ...] = ()


# --- tools, policy, approvals ---------------------------------------------------------------


class ToolsSpec(_Strict):
    manifests: tuple[str, ...] = Field(default=(), description="Globs of `kind: Tool` files.")
    require_manifest: bool = True
    max_output_bytes: int = Field(default=20_000, gt=0)


class PolicyRule(_Strict):
    id: str | None = None
    when: str = Field(description="cel-lite predicate over principal, tenant, task, tool, args.")
    effect: PolicyEffect
    reason: str | None = None


class PolicySpec(_Provider):
    use: str = "cel_lite"
    rules: tuple[PolicyRule, ...] = ()
    default_effect: PolicyEffect = PolicyEffect.ALLOW


class ApprovalsSpec(_Provider):
    use: str = "memory"
    timeout: Duration | None = None
    on_timeout: Literal["escalate", "reject"] = "escalate"
    approver_role: str | None = None


# --- budgets, state, observability, evals, prompts, sidecar -------------------------------


class BudgetsSpec(_Strict):
    per_run: Budget = Budget()


class StateSpec(_Provider):
    use: str = "memory"
    record: bool = Field(default=False, description="Record runs for `harnessweaver replay`.")


class ObservabilitySpec(_Provider):
    exporter: Literal["none", "console", "otlp"] = "none"
    endpoint: str | None = None
    capture_content: bool = Field(default=False, description="Post-redaction content only (R9).")
    configure_sdk: bool = False
    service_name: str | None = None


class OnlineEvalsSpec(_Strict):
    sample_rate: float = Field(default=0.0, ge=0, le=1)


class EvalsSpec(BaseModel):
    """``task: [files]`` entries, plus the reserved ``online`` key."""

    model_config = ConfigDict(frozen=True, extra="allow")

    online: OnlineEvalsSpec | None = None

    @model_validator(mode="after")
    def _suites_are_file_lists(self) -> Self:
        for task, files in (self.model_extra or {}).items():
            if not (isinstance(files, list) and all(isinstance(f, str) for f in files)):  # pyright: ignore[reportUnknownVariableType]
                raise ValueError(f"evals.{task} must be a list of dataset files")
        return self

    def suites(self) -> dict[str, tuple[str, ...]]:
        """Eval dataset files by task."""
        return {task: tuple(files) for task, files in (self.model_extra or {}).items()}


class PromptsSpec(_Strict):
    dir: str = "prompts"


class SidecarSpec(_Strict):
    url: str | None = None
    token_env: str = "HARNESSD_TOKEN"


# --- middleware -----------------------------------------------------------------------------


class MiddlewareSpec(_Provider):
    id: str | None = None
    use: str
    band: Band | None = Field(
        default=None,
        description="Defaults to the middleware's declared band; only profiles may use "
        "'baseline' (S8).",
    )
    hooks: tuple[HookPoint, ...] | None = Field(default=None, description="Narrow the hooks.")
    fail_mode: Literal["closed", "open"] | None = None
    timeout: Duration | None = None
    enabled: bool = True


# --- tasks ----------------------------------------------------------------------------------


class RunnerSpec(_Provider):
    use: str = "direct"


class TaskBudget(_Strict):
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


class TaskApprovals(_Strict):
    tools: tuple[str, ...] = ()
    approver_role: str | None = None
    timeout: Duration | None = None
    on_timeout: Literal["escalate", "reject"] | None = None


class TaskSpec(_Strict):
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


# --- documents ------------------------------------------------------------------------------


class RequireLevel(_Strict):
    default: Level = Level.L0
    tiers: dict[str, Level] = Field(default_factory=dict[str, Level])

    def for_tier(self, tier: str) -> Level:
        return self.tiers.get(tier, self.default)


class _Sections(_Strict):
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


class HarnessSpec(_Sections):
    """The effective spec of one app, after every layer is merged (DESIGNS No. 11)."""

    api_version: Literal["harnessweaver/v1"] = Field(default=API_VERSION, alias="apiVersion")
    kind: Literal["Harness"] = "Harness"
    metadata: Metadata
    extends: tuple[str, ...] = ()


class ProfileSpec(_Sections):
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
