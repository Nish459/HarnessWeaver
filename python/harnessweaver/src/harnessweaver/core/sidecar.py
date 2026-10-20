"""What apps send to ``harnessd``, the sidecar, over its HTTP/JSON API (DESIGNS No. 24).

The sidecar answers with contracts that already exist (``RunResult``,
``GuardResult``, ``ToolVerdict``, ``PolicyDecision``, ``SuiteResult``,
``ErrorInfo``); these models are the requests it takes, plus two small answers
of its own. The OpenAPI document in ``contracts/openapi`` is generated from them
(R11, ADR-0038).

The caller names the principal and tenant in each request: harnessd trusts the
app that holds its bearer token to say who it acts for, as an in-process
harness trusts the app's code (S6).
"""

from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator

from harnessweaver.core.envelope import Envelope, Labels, Principal
from harnessweaver.core.evals import EvalDataset
from harnessweaver.core.retrieval import ContextItem

__all__ = [
    "ApprovalAnswer",
    "AuthorizeRequest",
    "Caller",
    "CheckStage",
    "DecideRequest",
    "EvalRunRequest",
    "HookEntry",
    "ProviderCheck",
    "RunRequest",
    "SanitizeRequest",
    "SpecInfo",
    "StageCheck",
    "ValidateRequest",
]

CheckStage = Literal["input", "context", "output"]
"""The guard stages ``POST /v1/guards/{stage}`` runs; tool results go through
``POST /v1/tools/{name}/sanitize``."""


class _Wire(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class Caller(_Wire):
    """Who a check runs for. Each check is a one-step session (ADR-0038)."""

    principal: Principal | str = Field(default="anonymous", description="A principal or its id.")
    tenant: str = Field(default="default", min_length=1)
    task: str | None = Field(default=None, description="The task whose controls apply.")


class StageCheck(Caller):
    """``POST /v1/guards/{stage}``: content for ``input`` or ``output``; ``source`` and
    ``items`` for ``context``."""

    content: JsonValue = None
    source: str | None = Field(default=None, description="The context source, for 'context'.")
    query: str | None = None
    items: tuple[ContextItem, ...] = ()


class DecideRequest(Caller):
    """``POST /v1/decisions/{router}``: what a router decides on."""

    text: str | None = None
    options: tuple[str, ...] = ()
    state: dict[str, JsonValue] = Field(default_factory=dict[str, JsonValue])
    default: str | None = Field(default=None, description="The answer when no stage decides.")


class AuthorizeRequest(Caller):
    """``POST /v1/tools/{name}/authorize``: a call to decide on, never run."""

    args: dict[str, JsonValue] = Field(default_factory=dict[str, JsonValue])
    labels: Labels = Field(
        default=Labels(), description="What the caller's run has seen, for the trifecta check."
    )


class SanitizeRequest(Caller):
    """``POST /v1/tools/{name}/sanitize``: a result the caller's own tool returned."""

    arguments: dict[str, JsonValue] = Field(default_factory=dict[str, JsonValue])
    output: JsonValue = None
    is_error: bool = False


class ValidateRequest(Caller):
    """``POST /v1/validate``: a final output to check against a task."""

    # Narrowing a frozen model's field is sound: nothing can assign None to it later.
    task: str = Field(  # pyright: ignore[reportIncompatibleVariableOverride]
        min_length=1, description="The task whose output type and rules apply."
    )
    output: JsonValue = None


class RunRequest(_Wire):
    """``POST /v1/runs``: run a task to the end, or until it waits for approval."""

    task: str = Field(min_length=1)
    input: JsonValue = None
    principal: Principal | str = "anonymous"
    tenant: str = Field(default="default", min_length=1)
    idempotency_key: str | None = None
    budget: dict[str, JsonValue] | None = Field(
        default=None, description="Lower the task's overridable limits for this run (R10)."
    )
    attributes: dict[str, str] | None = None


class ApprovalAnswer(_Wire):
    """``POST /v1/runs/{run_id}/approvals/{approval_id}``: a human's answer."""

    decision: Literal["approve", "reject", "edit"] = "approve"
    approver: Principal | str
    edited_args: dict[str, JsonValue] | None = None
    reason: str | None = None


class ProviderCheck(_Wire):
    """``POST /v1/guards/providers/{name}:check``: one guardrail provider, run in the
    sidecar for a guard declared ``where: sidecar``."""

    content: str
    envelope: Envelope
    settings: dict[str, JsonValue] = Field(
        default_factory=dict[str, JsonValue], description="The provider's settings from the spec."
    )
    stage: str | None = Field(default=None, description="The guard's stage, checked if given.")


class EvalRunRequest(_Wire):
    """``POST /v1/evals/run``: a dataset, or one of the spec's own suite files."""

    dataset: EvalDataset | None = None
    file: str | None = Field(default=None, description="A file listed in the spec's evals.")

    @model_validator(mode="after")
    def _one_source(self) -> Self:
        if (self.dataset is None) == (self.file is None):
            raise ValueError("give either a dataset or a file")
        return self


class HookEntry(_Wire):
    """One middleware on a hook point, as ``GET /v1/hooks`` lists it, in run order."""

    name: str
    band: str
    fail_mode: Literal["closed", "open"]
    timeout_seconds: float | None = None


class SpecInfo(_Wire):
    """``GET /v1/spec``: the effective spec harnessd serves."""

    name: str
    api_version: str
    tasks: tuple[str, ...]
    level: str = Field(description="The adoption level the spec reaches, e.g. 'L3'.")
    required_level: str
    spec: dict[str, JsonValue] = Field(description="The merged spec, every layer applied.")
