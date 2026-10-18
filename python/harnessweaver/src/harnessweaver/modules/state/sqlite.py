"""The ``sqlite`` state store: durable runs and checkpoints in one SQLite file (ADR-0009).

A run suspended for approval can be resumed by another process that opens the
same file. SQLite calls run in worker threads so the event loop never blocks (C3).
"""

import sqlite3
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Final

import anyio.to_thread
from pydantic import BaseModel, ConfigDict, Field

from harnessweaver.core.plugins import provider
from harnessweaver.core.results import RunEvent
from harnessweaver.core.state import Checkpoint, RunRecord

__all__ = ["SqliteStateConfig", "SqliteStateStore"]

_SCHEMA: Final = """
CREATE TABLE IF NOT EXISTS runs (run_id TEXT PRIMARY KEY, data TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS checkpoints (run_id TEXT PRIMARY KEY, data TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS idempotency (
    tenant TEXT NOT NULL, task TEXT NOT NULL, key TEXT NOT NULL, run_id TEXT NOT NULL,
    PRIMARY KEY (tenant, task, key)
);
CREATE TABLE IF NOT EXISTS events (
    run_id TEXT NOT NULL, seq INTEGER NOT NULL, data TEXT NOT NULL,
    PRIMARY KEY (run_id, seq)
);
"""


class SqliteStateConfig(BaseModel):
    """Settings for the ``sqlite`` store."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    path: str = Field(
        default=".harness/state.db",
        description="Database file, relative to the working directory; ':memory:' for tests.",
    )


@provider(
    port="StateStore",
    name="sqlite",
    config=SqliteStateConfig,
    sample={"path": ":memory:"},
    deterministic=True,
    latency_class="fast",
)
class SqliteStateStore:
    """Runs, checkpoints, idempotency records and events in SQLite.

    The connection opens on first use, so building the store does no I/O.
    """

    def __init__(self, config: SqliteStateConfig | None = None) -> None:
        self._path = (config or SqliteStateConfig()).path
        self._connection: sqlite3.Connection | None = None
        self._lock = threading.Lock()

    def _connect(self) -> sqlite3.Connection:
        if self._connection is None:
            if self._path != ":memory:":
                Path(self._path).parent.mkdir(parents=True, exist_ok=True)
            connection = sqlite3.connect(self._path, check_same_thread=False, isolation_level=None)
            connection.execute("PRAGMA journal_mode=WAL")
            connection.executescript(_SCHEMA)
            self._connection = connection
        return self._connection

    async def _run[T](self, work: Callable[[sqlite3.Connection], T]) -> T:
        def locked() -> T:
            with self._lock:
                return work(self._connect())

        return await anyio.to_thread.run_sync(locked)

    async def put_run(self, record: RunRecord) -> None:
        data = record.model_dump_json()
        await self._run(
            lambda db: db.execute(
                "INSERT OR REPLACE INTO runs (run_id, data) VALUES (?, ?)", (record.run_id, data)
            )
        )

    async def get_run(self, run_id: str) -> RunRecord | None:
        row = await self._run(
            lambda db: db.execute("SELECT data FROM runs WHERE run_id = ?", (run_id,)).fetchone()
        )
        return RunRecord.model_validate_json(row[0]) if row else None

    async def put_checkpoint(self, checkpoint: Checkpoint) -> None:
        data = checkpoint.model_dump_json()
        await self._run(
            lambda db: db.execute(
                "INSERT OR REPLACE INTO checkpoints (run_id, data) VALUES (?, ?)",
                (checkpoint.run_id, data),
            )
        )

    async def get_checkpoint(self, run_id: str) -> Checkpoint | None:
        row = await self._run(
            lambda db: db.execute(
                "SELECT data FROM checkpoints WHERE run_id = ?", (run_id,)
            ).fetchone()
        )
        return Checkpoint.model_validate_json(row[0]) if row else None

    async def delete_checkpoint(self, run_id: str) -> None:
        await self._run(
            lambda db: db.execute("DELETE FROM checkpoints WHERE run_id = ?", (run_id,))
        )

    async def claim_idempotency(self, tenant: str, task: str, key: str, run_id: str) -> str:
        def claim(db: sqlite3.Connection) -> str:
            db.execute(
                "INSERT OR IGNORE INTO idempotency (tenant, task, key, run_id) VALUES (?, ?, ?, ?)",
                (tenant, task, key, run_id),
            )
            row = db.execute(
                "SELECT run_id FROM idempotency WHERE tenant = ? AND task = ? AND key = ?",
                (tenant, task, key),
            ).fetchone()
            return str(row[0])

        return await self._run(claim)

    async def append_event(self, event: RunEvent) -> None:
        data = event.model_dump_json()
        await self._run(
            lambda db: db.execute(
                "INSERT OR REPLACE INTO events (run_id, seq, data) VALUES (?, ?, ?)",
                (event.run_id, event.seq, data),
            )
        )

    async def events(self, run_id: str) -> list[RunEvent]:
        rows = await self._run(
            lambda db: db.execute(
                "SELECT data FROM events WHERE run_id = ? ORDER BY seq", (run_id,)
            ).fetchall()
        )
        return [RunEvent.model_validate_json(row[0]) for row in rows]

    async def aclose(self) -> None:
        def close(db: sqlite3.Connection) -> None:
            db.close()

        if self._connection is not None:
            await self._run(close)
            self._connection = None
