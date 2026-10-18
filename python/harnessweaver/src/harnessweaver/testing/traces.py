"""Asserting on what a run recorded (R13): ``assert_trace`` and friends."""

import json
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Any

from harnessweaver.core.results import RunResult
from harnessweaver.core.trace import RunTrace, TraceEvent, TraceKind

__all__ = ["Step", "assert_no_content", "assert_trace", "hooks_fired", "render_trace", "step"]


@dataclass(frozen=True, slots=True)
class Step:
    """What one expected trace event looks like. ``None`` fields match anything;
    ``reason`` matches a substring."""

    hook: str | None = None
    kind: str | None = None
    source: str | None = None
    outcome: str | None = None
    code: str | None = None
    band: str | None = None
    reason: str | None = None

    def matches(self, event: TraceEvent) -> bool:
        checks = (
            (self.hook, event.hook.value if event.hook else None),
            (self.kind, event.kind.value),
            (self.source, event.source),
            (self.outcome, event.outcome.value if event.outcome else None),
            (self.code, event.code),
            (self.band, event.band.value if event.band else None),
        )
        if any(want is not None and want != got for want, got in checks):
            return False
        return self.reason is None or self.reason in (event.reason or "")

    def __str__(self) -> str:
        fields = {
            k: getattr(self, k)
            for k in ("hook", "kind", "source", "outcome", "code", "band", "reason")
        }
        return "step(" + ", ".join(f"{k}={v!r}" for k, v in fields.items() if v is not None) + ")"


def step(
    hook: str | None = None,
    *,
    kind: str | None = None,
    source: str | None = None,
    outcome: str | None = None,
    code: str | None = None,
    band: str | None = None,
    reason: str | None = None,
) -> Step:
    """An expected trace event, for :func:`assert_trace`."""
    return Step(hook, kind, source, outcome, code, band, reason)


def _events(trace: RunResult | RunTrace | Iterable[TraceEvent]) -> list[TraceEvent]:
    if isinstance(trace, RunResult):
        return list(trace.trace)
    if isinstance(trace, RunTrace):
        return list(trace.events)
    return list(trace)


def hooks_fired(trace: RunResult | RunTrace | Iterable[TraceEvent]) -> list[str]:
    """The hook points that fired, in order (one entry per firing)."""
    return [e.hook.value for e in _events(trace) if e.kind is TraceKind.HOOK and e.hook]


def render_trace(trace: RunResult | RunTrace | Iterable[TraceEvent]) -> str:
    """The trace as text, one event per line, for assertion messages."""
    lines: list[str] = []
    for event in _events(trace):
        hook = event.hook.value if event.hook else "-"
        band = f" [{event.band.value}]" if event.band else ""
        outcome = f" -> {event.outcome.value}" if event.outcome else ""
        code = f" ({event.code})" if event.code else ""
        reason = f": {event.reason}" if event.reason else ""
        head = f"{event.seq:4d} {event.kind.value:<7} {hook:<17}"
        lines.append(f"{head} {event.source}{band}{outcome}{code}{reason}")
    return "\n".join(lines)


def assert_trace(
    trace: RunResult | RunTrace | Iterable[TraceEvent], *expected: str | Step, exact: bool = False
) -> None:
    """Check that the trace has the ``expected`` events, in that order.

    A string is a hook point that fired (``"tool.before"``); a :func:`step` matches any
    event by its fields. Other events may come in between, unless ``exact`` is set:
    then the expected strings must be exactly the hooks that fired.

    Raises:
        AssertionError: With the trace rendered, when something is missing.
    """
    events = _events(trace)
    steps = [Step(hook=s, kind="hook") if isinstance(s, str) else s for s in expected]
    if exact:
        if not all(isinstance(s, str) for s in expected):
            raise ValueError("exact=True takes hook names only")
        fired = hooks_fired(events)
        if fired != list(expected):
            raise AssertionError(
                f"hooks fired {fired}, expected {list(expected)}\n{render_trace(events)}"
            )
        return
    position = 0
    for want in steps:
        while position < len(events) and not want.matches(events[position]):
            position += 1
        if position == len(events):
            raise AssertionError(f"no {want} in order in the trace:\n{render_trace(events)}")
        position += 1


def _flatten(value: Any) -> str:
    if isinstance(value, RunResult | TraceEvent):
        return value.model_dump_json()
    if isinstance(value, RunTrace):
        return json.dumps([e.model_dump(mode="json") for e in value.events])
    if isinstance(value, str):
        return value
    if isinstance(value, Sequence) and not isinstance(value, bytes):
        return "\n".join(_flatten(v) for v in value)  # pyright: ignore[reportUnknownVariableType]
    return str(value)


def assert_no_content(where: Any, *values: str) -> None:
    """Check that none of ``values`` appears in ``where``: a result, a trace, log lines,
    span attributes or any mix of them (R9)."""
    text = _flatten(where)
    found = [v for v in values if v and v in text]
    if found:
        raise AssertionError(f"raw content leaked: {found}")
