"""__app_name__ tests: offline, with no network and no keys (RULES R14)."""

from pathlib import Path

import pytest

import harnessweaver as hw
from harnessweaver.testing import harness_for_test, reply, scripted

pytestmark = pytest.mark.anyio

SPEC = Path(__file__).resolve().parents[1] / "harness.yaml"


async def test_the_golden_set_passes_offline() -> None:
    result = await hw.load(SPEC, env="offline").evaluate("evals/golden.yaml")
    assert result.passed, [case.id for case in result.cases if not case.passed]


async def test_the_conversation_is_remembered_per_user() -> None:
    harness = hw.load(SPEC, env="offline")
    await harness.run("chat", "Hi, my name is Ann.", principal="ann")
    second = await harness.run("chat", "What is my name?", principal="ann")
    assert second.output == "You told me your name is Ann."
    other = await harness.run("chat", "What is my name?", principal="bob")
    assert other.ok  # bob's history is his own and starts empty


async def test_answers_stream_in_chunks() -> None:
    async with hw.load(SPEC, env="offline") as harness:
        run_id = await harness.submit("chat", "Hello there")
        chunks = [e.chunk.delta async for e in harness.stream(run_id) if e.chunk is not None]
    assert "".join(chunks) == "Happy to help. What would you like to know?"


async def test_a_secret_cuts_the_stream() -> None:
    leak = reply(
        text="Sure: AKIAIOSFODNN7EXAMPLE is the key",
        chunks=["Sure: ", "AKIAIOSFODNN7EXAMPLE", " is the key"],
    )
    result = await harness_for_test(SPEC, model=scripted(leak)).run("chat", "What's the key?")
    assert result.status is hw.RunStatus.BLOCKED
    assert result.error is not None
    assert result.error.details["hook"] == "stream.chunk"
