"""Logs go through loguru, stay silent until the app opts in, and never carry raw
content (ADR-0024, R9)."""

from collections.abc import Iterator

import pytest
from loguru import logger

import harnessweaver as hw
from harnessweaver.core.bus import HookBus
from harnessweaver.core.hooks import InputEvent
from harnessweaver.core.middleware import Registration
from harnessweaver.core.trace import RunTrace

pytestmark = pytest.mark.anyio

SECRET = "alice@example.com"


async def leaky(event: InputEvent, env: hw.Envelope) -> hw.Outcome | None:
    raise ValueError(f"can't handle {SECRET}")


@pytest.fixture
def logs() -> Iterator[list[str]]:
    lines: list[str] = []
    sink = logger.add(lines.append, level="TRACE", format="{name} | {message}")
    try:
        yield lines
    finally:
        logger.remove(sink)
        logger.disable("harnessweaver")


async def fail_open() -> None:
    registration = Registration(
        name="leaky",
        handler=leaky,
        hooks=frozenset({hw.HookPoint.INPUT_BEFORE}),
        band=hw.Band.APP,
        fail_mode="open",
    )
    clock = hw.FakeClock()
    envelope = hw.Envelope.new(tenant="t", principal="p", clock=clock)
    bus = HookBus([registration])
    await bus.emit(hw.HookPoint.INPUT_BEFORE, InputEvent(input=SECRET), envelope, RunTrace(clock))


async def test_the_core_is_silent_until_the_app_opts_in(logs: list[str]) -> None:
    await fail_open()
    assert logs == []
    logger.enable("harnessweaver")
    await fail_open()
    assert [line.strip() for line in logs] == [
        "harnessweaver.core.bus | middleware leaky failed on input.before (ValueError); "
        "fail_mode=open"
    ]


async def test_logs_name_the_error_type_never_its_message(logs: list[str]) -> None:
    logger.enable("harnessweaver")
    await fail_open()
    assert SECRET not in "".join(logs)
