"""The ``harness.yaml`` contract: the effective spec of one app (DESIGNS No. 11).

Sections that pick a provider with ``use:`` accept extra keys: those are the
provider's own settings, validated against the provider's config model when
the harness loads (still R4). Every other model rejects unknown keys.
"""

from harnessweaver.spec.models.base import API_VERSION, Level
from harnessweaver.spec.models.documents import HarnessSpec, ProfileSpec, RequireLevel
from harnessweaver.spec.models.sections import (
    ApprovalsSpec,
    BudgetsSpec,
    ContextSourceSpec,
    EvalsSpec,
    GuardrailsSpec,
    GuardSpec,
    Metadata,
    MiddlewareSpec,
    ModelsSpec,
    ObservabilitySpec,
    OnlineEvalsSpec,
    PluginsSpec,
    PolicyRule,
    PolicySpec,
    Price,
    PromptsSpec,
    RouterSpec,
    RoutingStage,
    SidecarSpec,
    StateSpec,
    ToolJudgeSpec,
    ToolsSpec,
    ValidationRule,
    ValidationSpec,
)
from harnessweaver.spec.models.tasks import RunnerSpec, TaskApprovals, TaskBudget, TaskSpec

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
    "ToolJudgeSpec",
    "ToolsSpec",
    "ValidationRule",
    "ValidationSpec",
]
