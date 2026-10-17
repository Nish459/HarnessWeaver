"""The ``memory`` state store: everything in this process, gone when it exits."""

from pydantic import BaseModel, ConfigDict

from harnessweaver.core.plugins import provider
from harnessweaver.core.results import RunEvent
from harnessweaver.core.state import Checkpoint, RunRecord

__all__ = ["MemoryStateConfig", "MemoryStateStore"]


class MemoryStateConfig(BaseModel):
    """The ``memory`` store takes no settings."""

    model_config = ConfigDict(extra="forbid", frozen=True)


@provider(
    port="StateStore",
    name="memory",
    config=MemoryStateConfig,
    deterministic=True,
    latency_class="fast",
)
class MemoryStateStore:
    """Runs, checkpoints, idempotency records and events, kept in dictionaries.

    Records are immutable models, so they are stored as they are.
    """

    def __init__(self, config: MemoryStateConfig | None = None) -> None:
        self._runs: dict[str, RunRecord] = {}
        self._checkpoints: dict[str, Checkpoint] = {}
        self._keys: dict[tuple[str, str, str], str] = {}
        self._events: dict[str, dict[int, RunEvent]] = {}

    async def put_run(self, record: RunRecord) -> None:
        self._runs[record.run_id] = record

    async def get_run(self, run_id: str) -> RunRecord | None:
        return self._runs.get(run_id)

    async def put_checkpoint(self, checkpoint: Checkpoint) -> None:
        self._checkpoints[checkpoint.run_id] = checkpoint

    async def get_checkpoint(self, run_id: str) -> Checkpoint | None:
        return self._checkpoints.get(run_id)

    async def delete_checkpoint(self, run_id: str) -> None:
        self._checkpoints.pop(run_id, None)

    async def claim_idempotency(self, tenant: str, task: str, key: str, run_id: str) -> str:
        return self._keys.setdefault((tenant, task, key), run_id)

    async def append_event(self, event: RunEvent) -> None:
        self._events.setdefault(event.run_id, {})[event.seq] = event

    async def events(self, run_id: str) -> list[RunEvent]:
        """Events in ``seq`` order; a repeated ``seq`` replaces the earlier event."""
        stored = self._events.get(run_id, {})
        return [stored[seq] for seq in sorted(stored)]

    async def aclose(self) -> None:
        return None
