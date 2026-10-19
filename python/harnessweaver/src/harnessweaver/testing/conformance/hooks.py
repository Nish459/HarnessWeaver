"""Checks on middleware, runners and adapters: the hooks they answer and fire (R4)."""

from typing import Any

from harnessweaver.core.envelope import Envelope
from harnessweaver.core.hooks import Band, HookPoint
from harnessweaver.core.middleware import MiddlewareDef, Registration
from harnessweaver.core.outcomes import Block, Continue, Escalate, Retry, Suspend
from harnessweaver.core.plugins import (
    AdapterInfo,
    RunnerInfo,
)
from harnessweaver.core.runs import RunStatus
from harnessweaver.testing.conformance.builds import build, sample_settings
from harnessweaver.testing.conformance.common import (
    CONDITIONAL_HOOKS,
    LIFECYCLE,
    Subject,
    conformance_env,
    expect,
)
from harnessweaver.testing.kit import harness_for_test, scripted
from harnessweaver.testing.samples import (
    AdapterSample,
    sample_event,
)
from harnessweaver.testing.traces import hooks_fired

__all__ = ["check_adapter", "check_middleware", "check_runner"]


async def check_middleware(subject: Subject) -> None:
    """Answers each declared hook with an outcome (or ``None``), never by raising."""
    item = subject.item
    if not isinstance(item, MiddlewareDef):
        return
    expect(item.band is not Band.BASELINE, "a middleware can't declare the baseline band (S8)")
    handler = build(subject.contribution)
    for hook in item.hooks:
        event = sample_event(hook, "hello")
        answer = await handler(event, conformance_env())
        expect(
            answer is None or isinstance(answer, Continue | Retry | Escalate | Suspend | Block),
            f"{subject.name} answered {hook.value} with {type(answer).__name__}",
        )
        if isinstance(answer, Continue) and answer.modified is not None:
            expect(type(answer.modified) is type(event), f"{subject.name} changed the payload type")


async def check_runner(subject: Subject) -> None:
    """A task runs to a final state and fires only hooks the runner declares (R4)."""
    item = subject.item
    if not isinstance(item, RunnerInfo):
        return
    runner = {"use": subject.name, **sample_settings(item.sample)}
    harness = harness_for_test(
        subject.spec(tasks={"conformance": {"runner": runner}}), model=scripted("ok")
    )
    result = await harness.run("conformance", "hello")
    expect(result.status.is_terminal or result.status is RunStatus.AWAITING_APPROVAL, result.status)
    fired = {HookPoint(h) for h in hooks_fired(result)}
    undeclared = fired - item.reaches
    expect(
        not undeclared,
        f"runner {subject.name} fired undeclared hooks {sorted(h.value for h in undeclared)}",
    )


async def check_adapter(subject: Subject) -> None:
    """One call through the adapter fires its declared hooks, in lifecycle order (R4)."""
    item = subject.item
    if not isinstance(item, AdapterInfo):
        return
    if item.sample is None:
        raise AssertionError(f"adapter {subject.name} needs sample= for conformance (T5)")
    sample = item.sample()
    expect(isinstance(sample, AdapterSample), "an adapter sample returns an AdapterSample")
    harness = harness_for_test(subject.spec())
    wrapped = harness.instrument(sample.target, adapter=subject.name)
    seen: list[HookPoint] = []

    async def record(event: Any, env: Envelope) -> None:
        seen.append(HookPoint(event.hook))

    harness._bus.add(
        Registration(
            name="conformance.audit",
            handler=record,
            hooks=frozenset(HookPoint),
            band=Band.APP,
            fail_mode="closed",
        )
    )
    await sample.call(wrapped)
    fired = set(seen)
    expect(
        fired <= item.reaches,
        f"fired undeclared hooks {sorted(h.value for h in fired - item.reaches)}",
    )
    missing = (item.reaches - CONDITIONAL_HOOKS) - fired
    expect(not missing, f"declared but didn't fire {sorted(h.value for h in missing)}")
    first: list[HookPoint] = []
    for hook in seen:
        if hook not in first:
            first.append(hook)
    expect(
        first == sorted(first, key=LIFECYCLE.index),
        f"hooks fired out of order: {[h.value for h in first]}",
    )
