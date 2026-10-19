"""Ports: the typed interfaces providers implement (DESIGNS No. 6, No. 12).

These Protocols are part of the public extension surface (``harnessweaver.ports``)
and are versioned with the contract (V1, V2). They use only HarnessWeaver types
(R7). Ports for modules that arrive later are added here as they land.
"""

import os
from collections.abc import AsyncIterator, Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Final, Protocol, runtime_checkable

from pydantic import JsonValue

from harnessweaver.core.decisions import Decision, DecisionRequest
from harnessweaver.core.envelope import Clock, Envelope
from harnessweaver.core.guards import GuardResult
from harnessweaver.core.manifests import ToolManifest
from harnessweaver.core.messages import ModelRequest, ModelResponse, StreamChunk, ToolCall, ToolSpec
from harnessweaver.core.policy import PolicyDecision, PolicyRequest
from harnessweaver.core.results import RunEvent
from harnessweaver.core.runs import ApprovalDecision, ApprovalRequest
from harnessweaver.core.state import Checkpoint, RunRecord
from harnessweaver.core.tools import SandboxLimits, SandboxResult, ToolInfo, ToolResult, ToolVerdict
from harnessweaver.core.trace import RunTrace

if TYPE_CHECKING:
    from harnessweaver.core.context import RunContext

__all__ = [
    "TEST_MODE_ENV",
    "ApprovalChannel",
    "Decider",
    "GovernedRun",
    "Guardrail",
    "ModelProvider",
    "PolicyEngine",
    "Runner",
    "Sandbox",
    "StateStore",
    "StreamingModelProvider",
    "TelemetrySetup",
    "ToolBackend",
    "ToolDescription",
    "ToolGovernor",
    "network_allowed",
]

TEST_MODE_ENV: Final = "HARNESSWEAVER_TEST_MODE"
"""Set to ``1`` to make live providers refuse network calls (R14)."""


def network_allowed() -> bool:
    """Whether live providers may call out. False when ``HARNESSWEAVER_TEST_MODE=1`` (R14)."""
    return os.environ.get(TEST_MODE_ENV) != "1"


class ModelProvider(Protocol):
    """Port ``ModelProvider``: answers a neutral :class:`ModelRequest` (DESIGNS No. 16).

    Providers translate to and from their vendor's API; no SDK type crosses this
    port (R7). Errors should be raised as ``ProviderError``.
    """

    async def generate(self, request: ModelRequest, env: Envelope) -> ModelResponse: ...


@runtime_checkable
class StreamingModelProvider(Protocol):
    """A ``ModelProvider`` that can also stream.

    ``stream`` yields :class:`StreamChunk` items and then one final
    :class:`ModelResponse` carrying the usage.
    """

    async def generate(self, request: ModelRequest, env: Envelope) -> ModelResponse: ...

    def stream(
        self, request: ModelRequest, env: Envelope
    ) -> AsyncIterator[StreamChunk | ModelResponse]: ...


@dataclass(frozen=True, slots=True)
class ToolDescription:
    """A tool as the governor sees it (``info``) and as a model sees it (``spec``).

    ``manifest`` is the tool's ``kind: Tool`` document; tools given in code (such as
    ``FakeTool``) have none and get the governor's defaults. ``digest_ok`` is false
    when the manifest's ``definition_digest`` doesn't match its definition, and
    then every call is blocked (S2).
    """

    info: ToolInfo
    spec: ToolSpec
    manifest: ToolManifest | None = None
    digest_ok: bool = True

    @classmethod
    def from_manifest(cls, manifest: ToolManifest) -> "ToolDescription":
        """Describe a tool by its manifest, checking its pinned digest (S2)."""
        pinned = manifest.spec.definition_digest
        return cls(
            manifest.info(),
            manifest.tool_spec(),
            manifest=manifest,
            digest_ok=pinned is None or pinned == manifest.computed_digest(),
        )


class ToolBackend(Protocol):
    """Finds and executes tools. The tools module builds one from manifests (S2)."""

    def describe(self, name: str) -> ToolDescription | None: ...

    async def execute(self, call: ToolCall, env: Envelope) -> ToolResult: ...


class StateStore(Protocol):
    """Port ``StateStore``: runs, checkpoints, idempotency records and the event log."""

    async def put_run(self, record: RunRecord) -> None: ...

    async def get_run(self, run_id: str) -> RunRecord | None: ...

    async def put_checkpoint(self, checkpoint: Checkpoint) -> None: ...

    async def get_checkpoint(self, run_id: str) -> Checkpoint | None: ...

    async def delete_checkpoint(self, run_id: str) -> None: ...

    async def claim_idempotency(self, tenant: str, task: str, key: str, run_id: str) -> str:
        """Record ``run_id`` for ``(tenant, task, key)`` unless one exists; return the owner."""
        ...

    async def append_event(self, event: RunEvent) -> None: ...

    async def events(self, run_id: str) -> list[RunEvent]: ...

    async def aclose(self) -> None: ...


class Guardrail(Protocol):
    """Port ``Guardrail``: checks one piece of content (DESIGNS No. 20)."""

    async def check(self, content: str, env: Envelope) -> GuardResult: ...


class Decider(Protocol):
    """Port ``Decider``: one routing stage (DESIGNS No. 19)."""

    async def __call__(self, request: DecisionRequest) -> Decision: ...


class TelemetrySetup(Protocol):
    """Port ``Telemetry``: sets up an OpenTelemetry SDK and exporter (R5, ADR-0010).

    Used only when ``observability.configure_sdk`` is true; the core itself only
    uses the OpenTelemetry API.
    """

    def configure(self, *, service_name: str, exporter: str, endpoint: str | None) -> None: ...


class Runner(Protocol):
    """Port ``Runner``: executes a task. Runners don't implement controls; hooks do.

    ``resume`` is the runner's own resume point from a checkpoint, or ``None``
    for a fresh run.
    """

    async def execute(
        self, ctx: "RunContext", input: Any, resume: Mapping[str, JsonValue] | None
    ) -> Any: ...


class PolicyEngine(Protocol):
    """Port ``PolicyEngine``: deterministic allow, deny or require-approval (R3).

    Providers must be declared ``deterministic=True`` and are built from
    :class:`~harnessweaver.core.policy.PolicyConfig` plus their own settings.
    They combine rules with :func:`~harnessweaver.core.policy.decide_by_rules`.
    """

    async def decide(self, request: PolicyRequest) -> PolicyDecision: ...


class Sandbox(Protocol):
    """Port ``Sandbox``: runs untrusted code away from the host process (S4).

    The code must not reach the host's files, network or environment. Errors in
    the code are returned in :class:`SandboxResult`, not raised.
    """

    async def run(
        self, code: str, inputs: Mapping[str, JsonValue], limits: SandboxLimits
    ) -> SandboxResult: ...


class ApprovalChannel(Protocol):
    """Port ``ApprovalChannel``: tells approvers a run is waiting for them (DESIGNS No. 18).

    The request is already saved when ``notify`` is called; answers come back
    through ``harness.approve``. A handler must not answer in-line.
    """

    async def notify(self, request: ApprovalRequest, env: Envelope) -> None: ...


class GovernedRun(Protocol):
    """What the governor reads from a run: its envelope, clock and trace."""

    trace: RunTrace

    @property
    def envelope(self) -> Envelope: ...

    @property
    def clock(self) -> Clock: ...


class ToolGovernor(Protocol):
    """What a governed tool call asks of the governor (DESIGNS No. 17, ADR-0025).

    ``authorize`` runs steps 1 to 7 on the call's final arguments, after the
    ``tool.before`` middleware; ``approval`` is the human answer the call
    carries, if any. ``sanitize`` is step 9.
    """

    async def authorize(
        self,
        ctx: GovernedRun,
        call: ToolCall,
        tool: ToolDescription,
        approval: ApprovalDecision | None,
    ) -> ToolVerdict: ...

    async def sanitize(
        self, ctx: GovernedRun, call: ToolCall, tool: ToolDescription, result: ToolResult
    ) -> ToolResult: ...
