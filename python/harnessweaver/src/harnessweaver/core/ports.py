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
from harnessweaver.core.envelope import Envelope
from harnessweaver.core.guards import GuardResult
from harnessweaver.core.messages import ModelRequest, ModelResponse, StreamChunk, ToolCall, ToolSpec
from harnessweaver.core.results import RunEvent
from harnessweaver.core.state import Checkpoint, RunRecord
from harnessweaver.core.tools import ToolInfo, ToolResult

if TYPE_CHECKING:
    from harnessweaver.core.context import RunContext

__all__ = [
    "TEST_MODE_ENV",
    "Decider",
    "Guardrail",
    "ModelProvider",
    "Runner",
    "StateStore",
    "StreamingModelProvider",
    "TelemetrySetup",
    "ToolBackend",
    "ToolDescription",
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
    """A tool as the governor sees it (``info``) and as a model sees it (``spec``)."""

    info: ToolInfo
    spec: ToolSpec


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
