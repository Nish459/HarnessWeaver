"""The spec's sections, one model each (``models``, ``guardrails``, ``budgets``, ...)."""

from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from harnessweaver.core.decisions import PolicyEffect
from harnessweaver.core.durations import Duration
from harnessweaver.core.envelope import Budget
from harnessweaver.core.guards import GuardAction
from harnessweaver.core.hooks import Band, HookPoint
from harnessweaver.spec.models.base import ProviderModel, StrictModel

__all__ = [
    "ApprovalsSpec",
    "BudgetsSpec",
    "ContextSourceSpec",
    "EvalsSpec",
    "GuardSpec",
    "GuardrailsSpec",
    "Metadata",
    "MiddlewareSpec",
    "ModelsSpec",
    "ObservabilitySpec",
    "OnlineEvalsSpec",
    "PluginsSpec",
    "PolicyRule",
    "PolicySpec",
    "Price",
    "PromptsSpec",
    "RouterSpec",
    "RoutingStage",
    "SidecarSpec",
    "StateSpec",
    "ToolsSpec",
    "ValidationRule",
    "ValidationSpec",
]

# --- metadata and plugins -----------------------------------------------------------------


class Metadata(StrictModel):
    name: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]*$")
    owner: str | None = None
    risk_tier: str = Field(default="internal", description="Picks the required level.")
    version: str | None = Field(default=None, description="SemVer; required for org profiles.")
    description: str | None = None


class PluginsSpec(StrictModel):
    local: tuple[str, ...] = Field(default=(), description="In-repo modules exposing `plugin`.")
    allow: tuple[str, ...] | None = Field(
        default=None, description="Plugin namespaces apps may use; usually locked by the org."
    )


# --- models -------------------------------------------------------------------------------


class Price(StrictModel):
    input_per_mtok: float = Field(ge=0, description="USD per million input tokens.")
    output_per_mtok: float = Field(ge=0, description="USD per million output tokens.")


class ModelsSpec(ProviderModel):
    provider: str | None = Field(default=None, description="e.g. 'openai.chat', 'scripted'.")
    default: str | None = Field(default=None, description="Default model alias.")
    aliases: dict[str, str] = Field(default_factory=dict[str, str])
    allowed_aliases: tuple[str, ...] | None = None
    prices: dict[str, Price] = Field(default_factory=dict[str, Price])


# --- routing ------------------------------------------------------------------------------


class RoutingStage(ProviderModel):
    id: str | None = None
    use: str
    threshold: float | None = Field(default=None, ge=0, le=1)


class RouterSpec(StrictModel):
    options: tuple[str, ...] = Field(min_length=1)
    cascade: tuple[RoutingStage, ...] = ()
    default: str | None = None

    @model_validator(mode="after")
    def _default_is_an_option(self) -> Self:
        if self.default is not None and self.default not in self.options:
            raise ValueError(f"default {self.default!r} is not one of the options")
        return self


# --- context ------------------------------------------------------------------------------


class ContextSourceSpec(ProviderModel):
    use: str
    label: Literal["untrusted", "trusted"] = "untrusted"
    max_items: int | None = Field(default=None, gt=0)
    max_tokens: int | None = Field(default=None, gt=0)


# --- guardrails and validation ------------------------------------------------------------


class GuardSpec(ProviderModel):
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


class GuardrailsSpec(StrictModel):
    input: tuple[GuardSpec, ...] = ()
    context: tuple[GuardSpec, ...] = ()
    tool_result: tuple[GuardSpec, ...] = ()
    output: tuple[GuardSpec, ...] = ()
    stream: tuple[GuardSpec, ...] = ()

    def all(self) -> tuple[GuardSpec, ...]:
        return self.input + self.context + self.tool_result + self.output + self.stream


class ValidationRule(StrictModel):
    id: str | None = None
    when: str = Field(
        description="cel-lite predicate over `output`, `input` and `task`; true means a violation."
    )
    message: str


class ValidationSpec(StrictModel):
    max_repairs: int = Field(default=1, ge=0)
    on_failure: Literal["escalate", "block"] = "block"
    rules: tuple[ValidationRule, ...] = ()


# --- tools, policy, approvals ---------------------------------------------------------------


class ToolsSpec(StrictModel):
    manifests: tuple[str, ...] = Field(default=(), description="Globs of `kind: Tool` files.")
    require_manifest: bool = True
    max_output_bytes: int = Field(default=20_000, gt=0)


class PolicyRule(StrictModel):
    id: str | None = None
    when: str = Field(description="cel-lite predicate over principal, tenant, task, tool, args.")
    effect: PolicyEffect
    reason: str | None = None


class PolicySpec(ProviderModel):
    use: str = "cel_lite"
    rules: tuple[PolicyRule, ...] = ()
    default_effect: PolicyEffect = PolicyEffect.ALLOW


class ApprovalsSpec(ProviderModel):
    use: str = "memory"
    timeout: Duration | None = None
    on_timeout: Literal["escalate", "reject"] = "escalate"
    approver_role: str | None = None


# --- budgets, state, observability, evals, prompts, sidecar -------------------------------


class BudgetsSpec(StrictModel):
    per_run: Budget = Budget()


class StateSpec(ProviderModel):
    use: str = "memory"
    record: bool = Field(default=False, description="Record runs for `harnessweaver replay`.")


class ObservabilitySpec(ProviderModel):
    exporter: Literal["none", "console", "otlp"] = "none"
    endpoint: str | None = None
    capture_content: bool = Field(default=False, description="Post-redaction content only (R9).")
    configure_sdk: bool = False
    service_name: str | None = None


class OnlineEvalsSpec(StrictModel):
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


class PromptsSpec(StrictModel):
    dir: str = "prompts"


class SidecarSpec(StrictModel):
    url: str | None = None
    token_env: str = "HARNESSD_TOKEN"


# --- middleware -----------------------------------------------------------------------------


class MiddlewareSpec(ProviderModel):
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
