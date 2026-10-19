"""What a harness keeps per task, per live run and per session."""

import contextlib
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Literal

import anyio
from anyio.streams.memory import MemoryObjectSendStream
from opentelemetry.trace import Span
from pydantic import JsonValue

from harnessweaver.core.context import RunContext, TaskInfo
from harnessweaver.core.envelope import Budget, Principal
from harnessweaver.core.ports import Runner
from harnessweaver.core.results import RunEvent, RunResult
from harnessweaver.core.state import RunRecord
from harnessweaver.spec.models import TaskSpec

__all__ = ["ActiveRun", "ApprovalAnswer", "Channel", "LiveRun", "PendingSession", "TaskEntry"]

type ApprovalAnswer = Literal["approve", "reject", "edit"]


@dataclass(slots=True)
class TaskEntry:
    name: str
    spec: TaskSpec
    info: TaskInfo
    runner: Runner
    runner_name: str
    resumable: bool


@dataclass(slots=True)
class Channel:
    """Live subscribers to one run's events."""

    seq: int = 0
    subscribers: list[MemoryObjectSendStream[RunEvent]] = field(
        default_factory=list[MemoryObjectSendStream[RunEvent]]
    )
    closed: bool = False


@dataclass(slots=True)
class LiveRun:
    """One run being driven by this harness."""

    record: RunRecord
    ctx: RunContext
    task: TaskEntry | None
    input: JsonValue
    channel: Channel


@dataclass(slots=True)
class ActiveRun:
    scope: anyio.CancelScope
    done: anyio.Event


@dataclass(slots=True)
class PendingSession:
    """A ``harness.session(...)`` call, before and after its run exists."""

    task: str | None
    principal: Principal | str
    tenant: str
    budget: Budget
    attributes: Mapping[str, str] | None
    run: LiveRun | None = None
    stack: contextlib.ExitStack | None = None
    span: Span | None = None
    result: RunResult | None = None
