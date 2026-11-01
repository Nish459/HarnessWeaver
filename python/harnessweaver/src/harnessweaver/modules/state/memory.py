"""The ``memory`` state store: everything in this process, gone when it exits."""

from pydantic import BaseModel, ConfigDict

from harnessweaver.core.evals import OnlineSample
from harnessweaver.core.plugins import provider
from harnessweaver.core.results import RunEvent
from harnessweaver.core.state import Checkpoint, RecordedCall, RunRecord

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
    """Runs, checkpoints, idempotency records, events, recordings and online samples,
    kept in dictionaries.

    Records are immutable models, so they are stored as they are.
    """

    def __init__(self, config: MemoryStateConfig | None = None) -> None:
        self._runs: dict[str, RunRecord] = {}
        self._checkpoints: dict[str, Checkpoint] = {}
        self._keys: dict[tuple[str, str, str], str] = {}
        self._events: dict[str, dict[int, RunEvent]] = {}
        self._recordings: dict[str, dict[int, RecordedCall]] = {}
        self._samples: dict[str, OnlineSample] = {}

    async def put_run(self, record: RunRecord) -> None:
        self._runs[record.run_id] = record

    async def get_run(self, run_id: str) -> RunRecord | None:
        return self._runs.get(run_id)

    async def put_checkpoint(self, checkpoint: Checkpoint) -> None:
        self._checkpoints[checkpoint.run_id] = checkpoint

    async def get_checkpoint(self, run_id: str) -> Checkpoint | None:
        return self._checkpoints.get(run_id)

    async def claim_approval(self, checkpoint: Checkpoint, approval_id: str) -> bool:
        """Atomic because nothing here awaits, and one event loop owns this store."""
        stored = self._checkpoints.get(checkpoint.run_id)
        if stored is None or stored.approval is None or stored.approval.approval_id != approval_id:
            return False
        self._checkpoints[checkpoint.run_id] = checkpoint
        return True

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

    async def append_recording(self, call: RecordedCall) -> None:
        self._recordings.setdefault(call.run_id, {})[call.seq] = call

    async def recording(self, run_id: str) -> list[RecordedCall]:
        stored = self._recordings.get(run_id, {})
        return [stored[seq] for seq in sorted(stored)]

    async def put_sample(self, sample: OnlineSample) -> None:
        self._samples.pop(sample.run_id, None)
        self._samples[sample.run_id] = sample

    async def samples(self, task: str | None = None) -> list[OnlineSample]:
        return [s for s in self._samples.values() if task is None or s.task == task]

    async def aclose(self) -> None:
        return None
