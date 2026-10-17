"""State stores (memory and SQLite behave the same) and the prompt store."""

from datetime import UTC, datetime
from pathlib import Path

import pytest

import harnessweaver as hw
from harnessweaver.core.state import Checkpoint, RunRecord
from harnessweaver.errors import SpecError
from harnessweaver.modules.prompts import PromptStore
from harnessweaver.modules.state import (
    MemoryStateStore,
    SqliteStateConfig,
    SqliteStateStore,
)
from harnessweaver.ports import StateStore

pytestmark = pytest.mark.anyio

NOW = datetime(2026, 1, 5, 9, 0, tzinfo=UTC)


def record(run_id: str, status: hw.RunStatus = hw.RunStatus.PENDING) -> RunRecord:
    envelope = hw.Envelope.new(tenant="t", principal="alice", run_id=run_id)
    return RunRecord(
        run_id=run_id,
        tenant="t",
        task="x",
        status=status,
        envelope=envelope,
        input={"a": 1},
        created_at=NOW,
        updated_at=NOW,
    )


@pytest.fixture(params=["memory", "sqlite"])
async def store(request: pytest.FixtureRequest, tmp_path: Path) -> StateStore:
    if request.param == "memory":
        return MemoryStateStore()
    return SqliteStateStore(SqliteStateConfig(path=str(tmp_path / "deep" / "state.db")))


async def test_runs_checkpoints_keys_and_events(store: StateStore) -> None:
    assert await store.get_run("r1") is None
    await store.put_run(record("r1"))
    await store.put_run(record("r1", hw.RunStatus.RUNNING))
    found = await store.get_run("r1")
    assert found is not None
    assert found.status is hw.RunStatus.RUNNING
    assert found.input == {"a": 1}

    assert await store.get_checkpoint("r1") is None
    await store.put_checkpoint(Checkpoint(run_id="r1", resume={"step": 2}))
    checkpoint = await store.get_checkpoint("r1")
    assert checkpoint is not None
    assert checkpoint.resume == {"step": 2}
    await store.delete_checkpoint("r1")
    await store.delete_checkpoint("r1")
    assert await store.get_checkpoint("r1") is None

    assert await store.claim_idempotency("t", "x", "k", "r1") == "r1"
    assert await store.claim_idempotency("t", "x", "k", "r2") == "r1"
    assert await store.claim_idempotency("t2", "x", "k", "r2") == "r2"

    for seq in (1, 0, 2):
        event = hw.RunEvent(
            run_id="r1", seq=seq, at=NOW, type="status", status=hw.RunStatus.RUNNING
        )
        await store.append_event(event)
    assert [e.seq for e in await store.events("r1")] == [0, 1, 2]
    assert await store.events("r2") == []
    await store.aclose()
    await store.aclose()


async def test_sqlite_keeps_data_across_instances(tmp_path: Path) -> None:
    config = SqliteStateConfig(path=str(tmp_path / "state.db"))
    first = SqliteStateStore(config)
    await first.put_run(record("r1"))
    await first.aclose()
    second = SqliteStateStore(config)
    assert await second.get_run("r1") is not None
    await second.aclose()
    in_memory = SqliteStateStore(SqliteStateConfig(path=":memory:"))
    assert await in_memory.get_run("r1") is None
    await in_memory.aclose()


def write_prompts(directory: Path, names: list[str]) -> PromptStore:
    directory.mkdir(parents=True, exist_ok=True)
    for name in names:
        (directory / name).write_text(f"{name}: {{topic}} {{{{literal}}}}", encoding="ascii")
    return PromptStore(directory)


async def test_prompt_versions_resolve(tmp_path: Path) -> None:
    prompts = write_prompts(
        tmp_path / "prompts",
        [
            "answer@1.0.0.md",
            "answer@1.2.0.md",
            "answer@2.0.0.txt",
            "answer@4.md",
            "plain.md",
            "notes.json",
        ],
    )
    assert prompts.directory == tmp_path / "prompts"
    assert prompts.find("answer@1.0.0").version == "1.0.0"
    assert prompts.find("answer@^1").version == "1.2.0"
    assert prompts.find("answer@1").version == "1.2.0"
    assert prompts.find("answer").version == "2.0.0"
    assert prompts.find("answer@4").ref == "answer@4"
    assert prompts.find("plain").ref == "plain"
    assert (
        await prompts.render("answer@2", {"topic": "refunds"})
        == "answer@2.0.0.txt: refunds {literal}"
    )
    for missing in ("answer@3", "absent", "answer@not a range"):
        with pytest.raises(SpecError):
            prompts.find(missing)


async def test_prompt_rendering_errors(tmp_path: Path) -> None:
    directory = tmp_path / "p"
    directory.mkdir()
    (directory / "bad@1.md").write_text("{0}", encoding="ascii")
    (directory / "attr@1.md").write_text("{topic.upper}", encoding="ascii")
    (directory / "good@1.md").write_text("{topic}", encoding="ascii")
    prompts = PromptStore(directory)
    with pytest.raises(SpecError, match="malformed"):
        await prompts.render("bad@1", {})
    with pytest.raises(SpecError, match="malformed"):
        await prompts.render("attr@1", {"topic": 3})
    with pytest.raises(SpecError, match="wasn't given"):
        await prompts.render("good@1", {})
    assert PromptStore(tmp_path / "absent")._prompts() == {}
