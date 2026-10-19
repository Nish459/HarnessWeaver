"""Checks on what contributions return: valid results, determinism, timeouts."""

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import timedelta
from typing import Any

import anyio

from harnessweaver.core.bus import HookBus
from harnessweaver.core.decisions import Decision
from harnessweaver.core.envelope import Envelope, FakeClock
from harnessweaver.core.errors import ProviderError
from harnessweaver.core.guards import GuardAction, GuardResult
from harnessweaver.core.hooks import Band, HookPoint
from harnessweaver.core.messages import ModelResponse, StreamChunk
from harnessweaver.core.middleware import Registration
from harnessweaver.core.outcomes import Block
from harnessweaver.core.plugins import (
    ProviderInfo,
)
from harnessweaver.core.ports import StreamingModelProvider
from harnessweaver.core.results import RunEvent
from harnessweaver.core.runs import RunStatus
from harnessweaver.core.state import Checkpoint, RunRecord
from harnessweaver.modules.guardrails import Guard, guard_handler
from harnessweaver.testing.conformance.builds import build
from harnessweaver.testing.conformance.common import Subject, conformance_env, expect
from harnessweaver.testing.kit import harness_for_test, output, scripted
from harnessweaver.testing.samples import (
    CANARY,
    SAMPLE_TEXTS,
    sample_decision_request,
    sample_event,
    sample_request,
)

__all__ = ["check_deterministic", "check_results", "check_timeout_blocks", "session_run"]


@contextmanager
def session_run() -> Iterator[Any]:
    """A harness whose scripted model also answers ``llm.judge``-style questions."""
    yield harness_for_test({}, model=scripted(output({"pass": True, "reason": "fine"})))


async def guard_results(provider: Any) -> list[GuardResult]:
    with session_run() as harness:
        async with harness.session() as session:
            return [await provider.check(text, session.envelope) for text in SAMPLE_TEXTS]


async def model_results(provider: Any) -> list[ModelResponse] | None:
    """Two calls (one streamed, if supported), or ``None`` if the provider refused the
    network as live providers must in test mode."""
    try:
        results = [await provider.generate(sample_request(), conformance_env())]
        if isinstance(provider, StreamingModelProvider):
            items = [item async for item in provider.stream(sample_request(), conformance_env())]
            expect(items, "stream yielded nothing")
            expect(isinstance(items[-1], ModelResponse), "a stream must end with the ModelResponse")
            expect(
                all(isinstance(i, StreamChunk) for i in items[:-1]),
                "a stream yields StreamChunks first",
            )
            results.append(items[-1])
    except ProviderError as exc:
        expect(CANARY not in exc.message)
        return None
    return results


async def _state_contract(store: Any) -> None:
    from harnessweaver.core.envelope import Envelope as _Envelope

    now = FakeClock().now()
    envelope = _Envelope.new(tenant="t", principal="p", run_id="run_conformance")
    record = RunRecord(
        run_id="run_conformance",
        tenant="t",
        task="x",
        status=RunStatus.PENDING,
        envelope=envelope,
        created_at=now,
        updated_at=now,
    )
    await store.put_run(record)
    found = await store.get_run("run_conformance")
    expect(found is not None and found.run_id == "run_conformance", "put_run/get_run round trip")
    expect(await store.get_run("run_missing") is None)
    await store.put_checkpoint(Checkpoint(run_id="run_conformance", resume={"step": 1}))
    checkpoint = await store.get_checkpoint("run_conformance")
    expect(checkpoint is not None and checkpoint.resume == {"step": 1}, "checkpoint round trip")
    await store.delete_checkpoint("run_conformance")
    expect(await store.get_checkpoint("run_conformance") is None)
    expect(await store.claim_idempotency("t", "x", "k", "run_a") == "run_a")
    expect(await store.claim_idempotency("t", "x", "k", "run_b") == "run_a", "idempotency claim")
    for seq in (2, 0, 1):
        await store.append_event(RunEvent(run_id="run_conformance", seq=seq, at=now, type="status"))
    expect(
        [e.seq for e in await store.events("run_conformance")] == [0, 1, 2], "events in seq order"
    )
    await store.aclose()


async def check_results(subject: Subject) -> None:
    """Results validate against the contract for the provider's port."""
    item = subject.item
    if not isinstance(item, ProviderInfo):
        return
    provider = build(subject.contribution)
    if item.port == "Guardrail":
        for result in await guard_results(provider):
            expect(isinstance(result, GuardResult), f"{item.name} returned {type(result).__name__}")
            GuardResult.model_validate(result.model_dump())
            if result.action is GuardAction.REDACT:
                expect(result.content is not None, "a redact result needs content")
            for finding in result.findings:
                expect(CANARY not in finding.type, "findings must not hold raw content (R9)")
    elif item.port == "Decider":
        decision = await provider(sample_decision_request())
        expect(isinstance(decision, Decision), f"{item.name} returned {type(decision).__name__}")
        if decision.choice is not None:
            expect(
                decision.choice in sample_decision_request().options,
                "a choice must be one of the options",
            )
    elif item.port == "ModelProvider":
        for response in await model_results(provider) or []:
            ModelResponse.model_validate(response.model_dump())
    elif item.port == "StateStore":
        await _state_contract(provider)
    elif item.port == "Telemetry":
        expect(
            callable(getattr(provider, "configure", None)), "a Telemetry setup needs configure()"
        )


async def check_deterministic(subject: Subject) -> None:
    """Fresh instances of a deterministic provider give the same results for the same input."""
    item = subject.item
    if not isinstance(item, ProviderInfo) or not item.deterministic:
        return
    if item.port == "Guardrail":
        first, second = (
            await guard_results(build(subject.contribution)),
            await guard_results(build(subject.contribution)),
        )
        expect(first == second, f"{item.name} answered differently the second time")
    elif item.port == "Decider":
        expect(
            await build(subject.contribution)(sample_decision_request())
            == await build(subject.contribution)(sample_decision_request())
        )
    elif item.port == "ModelProvider":
        first_model = await model_results(build(subject.contribution))
        second_model = await model_results(build(subject.contribution))
        expect(first_model == second_model, f"{item.name} answered differently the second time")


class _Slow:
    def __init__(self, inner: Any) -> None:
        self.inner = inner

    async def check(self, content: str, env: Envelope) -> GuardResult:
        result = await self.inner.check(content, env)
        await anyio.sleep(1)
        return result


async def check_timeout_blocks(subject: Subject) -> None:
    """A guard that runs past its timeout blocks when it fails closed, and is cancellable."""
    item = subject.item
    if not isinstance(item, ProviderInfo) or item.port != "Guardrail":
        return
    stage = item.stages[0] if item.stages else "input"
    hook = {
        "input": HookPoint.INPUT_BEFORE,
        "context": HookPoint.CONTEXT_AFTER,
        "tool_result": HookPoint.TOOL_AFTER,
        "output": HookPoint.OUTPUT_BEFORE,
        "stream": HookPoint.STREAM_CHUNK,
    }[stage]
    with session_run() as harness:
        async with harness.session() as session:
            guard = Guard(id="slow", provider=_Slow(build(subject.contribution)))
            bus = HookBus(
                [
                    Registration(
                        name="slow",
                        handler=guard_handler(stage, [guard], "slow"),  # pyright: ignore[reportArgumentType]
                        hooks=frozenset({hook}),
                        band=Band.BASELINE,
                        fail_mode="closed",
                        timeout=timedelta(milliseconds=20),
                    )
                ]
            )
            result = await bus.emit(
                hook, sample_event(hook, "hello"), session.envelope, session.trace
            )
            outcome = result.outcome
            if not isinstance(outcome, Block):
                raise AssertionError(f"expected Block, got {outcome.kind}")
            expect(outcome.code == "middleware_timeout", f"expected a timeout, got {outcome.code}")
            provider = build(subject.contribution)
            with anyio.CancelScope() as scope:
                scope.cancel()
                await provider.check("hello", session.envelope)
