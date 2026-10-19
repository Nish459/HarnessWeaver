"""The parts every layer of a harness shares: spec, bus, tasks, state and run events."""

import math
from collections.abc import AsyncIterator, Mapping, Sequence
from typing import Any

import anyio
from anyio.abc import TaskGroup

from harnessweaver.core.budgets import BudgetMeter
from harnessweaver.core.bus import HookBus
from harnessweaver.core.context import ModelAccess, RunContext, TaskInfo
from harnessweaver.core.envelope import Clock, Envelope
from harnessweaver.core.errors import (
    NotFound,
)
from harnessweaver.core.hooks import HookPoint
from harnessweaver.core.messages import StreamChunk
from harnessweaver.core.middleware import Registration
from harnessweaver.core.plugins import RunnerInfo
from harnessweaver.core.ports import StateStore, ToolBackend
from harnessweaver.core.registry import Registry
from harnessweaver.core.results import RunEvent
from harnessweaver.core.state import Grant
from harnessweaver.core.telemetry import Telemetry
from harnessweaver.core.trace import RunTrace, TraceEvent
from harnessweaver.harness.records import ActiveRun, Channel, LiveRun, TaskEntry
from harnessweaver.modules.prompts import PromptStore
from harnessweaver.spec.explain import ExplainRow
from harnessweaver.spec.loader import EffectiveSpec

__all__ = ["HarnessBase"]


class HarnessBase:
    """A harness's parts, its introspection, and the events of its runs."""

    def __init__(
        self,
        effective: EffectiveSpec,
        *,
        registry: Registry,
        bus: HookBus,
        tasks: Mapping[str, TaskEntry],
        models: ModelAccess,
        state: StateStore,
        prompts: PromptStore,
        tools: ToolBackend | None,
        clock: Clock,
        telemetry: Telemetry | None = None,
    ) -> None:
        self._effective = effective
        self._telemetry = telemetry or Telemetry()
        self._registry = registry
        self._bus = bus
        self._tasks = dict(tasks)
        self._models = models
        self._state = state
        self._prompts = prompts
        self._tools = tools
        self._clock = clock
        self._group: TaskGroup | None = None
        self._active: dict[str, ActiveRun] = {}
        self._channels: dict[str, Channel] = {}

    # --- introspection ----------------------------------------------------------------------

    @property
    def spec(self) -> EffectiveSpec:
        """The effective spec this harness was built from."""
        return self._effective

    @property
    def name(self) -> str:
        return self._effective.spec.metadata.name

    @property
    def registry(self) -> Registry:
        return self._registry

    @property
    def tasks(self) -> list[str]:
        return sorted(self._tasks)

    def explain(self) -> list[ExplainRow]:
        """Every effective value with its layer, lock and bounds (``spec explain``)."""
        return self._effective.explain()

    def runner_of(self, task: str) -> RunnerInfo:
        """The runner a task uses, with the hook points it reaches.

        Raises:
            NotFound: For an unknown task.
        """
        return self._registry.runner(self._task(task).runner_name)

    def hooks(self, task: str | None = None) -> dict[HookPoint, list[Registration]]:
        """The middleware chain of every hook point, in execution order."""
        return {hook: self._bus.chain(hook, task) for hook in HookPoint}

    def _task(self, task: str) -> TaskEntry:
        found = self._tasks.get(task)
        if found is None:
            raise NotFound(f"unknown task {task!r}; tasks: {', '.join(self.tasks)}", task=task)
        return found

    def _context(
        self,
        envelope: Envelope,
        task: TaskInfo | None,
        channel: Channel,
        *,
        meter: BudgetMeter,
        trace_events: tuple[TraceEvent, ...] = (),
        grants: Sequence[Grant] = (),
        can_suspend: bool = True,
    ) -> RunContext:
        run_id = envelope.run_id

        def on_trace(event: TraceEvent) -> None:
            self._publish(run_id, channel, "trace", trace=event)
            self._telemetry.trace_event(event)

        def on_chunk(chunk: StreamChunk) -> None:
            self._publish(run_id, channel, "chunk", chunk=chunk)

        return RunContext(
            envelope=envelope,
            bus=self._bus,
            trace=RunTrace(self._clock, events=trace_events, on_event=on_trace),
            meter=meter,
            models=self._models,
            tools=self._tools,
            task=task,
            prompts=self._prompts,
            grants=grants,
            on_chunk=on_chunk,
            harness=self,
            can_suspend=can_suspend,
            telemetry=self._telemetry,
        )

    # --- events -----------------------------------------------------------------------------

    def _publish(self, run_id: str, channel: Channel, type_: str, **fields: Any) -> RunEvent:
        event = RunEvent.model_validate(
            {"run_id": run_id, "seq": channel.seq, "at": self._clock.now(), "type": type_, **fields}
        )
        channel.seq += 1
        for subscriber in list(channel.subscribers):
            try:
                subscriber.send_nowait(event)
            except (anyio.BrokenResourceError, anyio.ClosedResourceError):
                channel.subscribers.remove(subscriber)
        return event

    async def _event(self, run: LiveRun, type_: str, **fields: Any) -> None:
        event = self._publish(run.ctx.run_id, run.channel, type_, **fields)
        await self._state.append_event(event)

    def _close(self, channel: Channel) -> None:
        channel.closed = True
        for subscriber in channel.subscribers:
            subscriber.close()
        channel.subscribers.clear()

    async def stream(self, run_id: str) -> AsyncIterator[RunEvent]:
        """Yield a run's events: its stored history, then live events until it stops.

        ``status`` and ``approval`` events come from the state store; ``trace`` and
        ``chunk`` events are only seen while the run is live in this process.
        """
        channel = self._channels.get(run_id)
        if channel is None or channel.closed:
            for event in await self._state.events(run_id):
                yield event
            return
        send, receive = anyio.create_memory_object_stream[RunEvent](math.inf)
        channel.subscribers.append(send)
        seen: set[int] = set()
        for event in await self._state.events(run_id):
            seen.add(event.seq)
            yield event
        async with receive:
            async for event in receive:
                if event.type in ("status", "approval") and event.seq in seen:
                    continue
                yield event
