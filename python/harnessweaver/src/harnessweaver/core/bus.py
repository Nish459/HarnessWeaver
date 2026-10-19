"""The hook bus: runs middleware for one hook event and combines their answers (DESIGNS No. 8).

Rules (fixtures suites ``hook_order`` and ``bus``):

1. Middleware runs in bands, ``baseline`` -> ``platform`` -> ``app`` -> ``task``,
   and in registration order within a band.
2. Inbound hooks run outermost-first; outbound hooks run innermost-first.
3. ``Continue(modified=...)`` hands the new payload to the next middleware.
4. ``Block`` stops the chain: nothing can outrank it.
5. A middleware that raises or times out is handled by its fail mode:
   ``closed`` -> ``Block``, ``open`` -> ``Continue`` and a log line (R2).
6. The most severe outcome wins; every outcome is traced (R13).
"""

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

import anyio
from loguru import logger

from harnessweaver.core.envelope import Envelope
from harnessweaver.core.errors import SpecError
from harnessweaver.core.hooks import EVENT_TYPES, Band, HookPoint, execution_order
from harnessweaver.core.middleware import Registration
from harnessweaver.core.outcomes import (
    Block,
    Continue,
    Escalate,
    Outcome,
    Retry,
    Suspend,
    most_severe,
)
from harnessweaver.core.trace import RunTrace

__all__ = ["HookBus", "HookResult"]


_OUTCOME_TYPES = (Continue, Retry, Escalate, Suspend, Block)


@dataclass(frozen=True, slots=True)
class HookResult[E]:
    """The combined outcome of one hook event, and the payload after every modification."""

    hook: HookPoint
    outcome: Outcome
    event: E

    @property
    def halted(self) -> bool:
        """Whether the run can't go on: ``Block``, ``Suspend`` or ``Escalate``."""
        return isinstance(self.outcome, Block | Suspend | Escalate)


class _BadAnswer(TypeError):
    """A middleware returned something that isn't a valid outcome for this event."""


def _checked(answer: object, payload: object, name: str) -> Outcome:
    if answer is None:
        return Continue()
    if not isinstance(answer, _OUTCOME_TYPES):
        raise _BadAnswer(f"middleware {name} returned {type(answer).__name__}, not an outcome")
    modified = answer.modified if isinstance(answer, Continue) else None
    if modified is not None and type(modified) is not type(payload):
        raise _BadAnswer(
            f"middleware {name} modified the payload into a "
            f"{type(modified).__name__}, not a {type(payload).__name__}"
        )
    return answer


def _failure_outcome(registration: Registration, error_type: str, timed_out: bool) -> Outcome:
    if registration.fail_mode == "open":
        return Continue()
    if timed_out:
        return Block(reason=f"middleware {registration.name} timed out", code="middleware_timeout")
    return Block(
        reason=f"middleware {registration.name} failed ({error_type})", code="middleware_error"
    )


class HookBus:
    """The middleware installed on one harness, and the algorithm that runs it (C4)."""

    def __init__(self, registrations: Iterable[Registration] = ()) -> None:
        self._registrations: list[Registration] = []
        for registration in registrations:
            self.add(registration)

    def add(self, registration: Registration) -> None:
        """Install a middleware.

        Raises:
            SpecError: If a baseline-band middleware fails open (R2).
        """
        if registration.band is Band.BASELINE and registration.fail_mode != "closed":
            raise SpecError(
                f"middleware {registration.name} is in the baseline band but fails open; "
                f"baseline middleware must fail closed (RULES R2)",
                name=registration.name,
            )
        self._registrations.append(registration)

    @property
    def registrations(self) -> tuple[Registration, ...]:
        return tuple(self._registrations)

    def chain(self, hook: HookPoint, task: str | None = None) -> list[Registration]:
        """The middleware that run for ``hook``, in execution order."""
        applicable = [r for r in self._registrations if r.applies_to(hook, task)]
        return execution_order(applicable, hook, lambda r: r.band)

    def hooks_in_band(self, band: Band, task: str | None = None) -> frozenset[HookPoint]:
        """Hook points that have middleware in ``band`` for ``task``."""
        return frozenset(
            hook
            for r in self._registrations
            if r.band is band and (r.tasks is None or task in r.tasks)
            for hook in r.hooks
        )

    async def emit[E](
        self,
        hook: HookPoint,
        event: E,
        env: Envelope,
        trace: RunTrace,
        *,
        task: str | None = None,
        source: str = "harness",
    ) -> HookResult[E]:
        """Run every middleware for ``hook`` on ``event`` and combine the outcomes.

        Raises:
            TypeError: If ``event`` isn't the payload type of ``hook``.
        """
        if not isinstance(event, EVENT_TYPES[hook]):
            raise TypeError(f"{hook} carries {EVENT_TYPES[hook].__name__}, not {type(event)}")
        payload: Any = event
        chain = self.chain(hook, task)
        outcomes: list[Outcome] = []
        for registration in chain:
            try:
                if registration.timeout is not None:
                    with anyio.fail_after(registration.timeout.total_seconds()):
                        answer = await registration.handler(payload, env)
                else:
                    answer = await registration.handler(payload, env)
                outcome = _checked(answer, payload, registration.name)
            except Exception as exc:
                timed_out = isinstance(exc, TimeoutError)
                error_type = type(exc).__name__
                outcome = _failure_outcome(registration, error_type, timed_out)
                trace.failure(
                    hook,
                    registration.name,
                    registration.band,
                    outcome,
                    error_type=error_type,
                    timed_out=timed_out,
                )
                # Only the exception type: its message may hold raw content (R9).
                logger.warning(
                    "middleware {} failed on {} ({}); fail_mode={}",
                    registration.name,
                    hook.value,
                    error_type,
                    registration.fail_mode,
                )
            else:
                trace.outcome(hook, registration.name, registration.band, outcome)
            outcomes.append(outcome)
            if isinstance(outcome, Continue) and outcome.modified is not None:
                payload = outcome.modified
            if isinstance(outcome, Block):
                break
        combined = most_severe(outcomes)
        trace.hook(hook, source, combined, middleware=len(chain))
        return HookResult(hook, combined, payload)
