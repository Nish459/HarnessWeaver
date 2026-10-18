"""Building harnesses for tests: scripted replies, fake tools, fake routing (RULES T2)."""

import inspect
from collections.abc import Awaitable, Callable, Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pydantic import JsonValue

from harnessweaver.core.decisions import Decision, DecisionKind, DecisionRequest
from harnessweaver.core.envelope import Clock, Envelope, FakeClock
from harnessweaver.core.hooks import Band, HookPoint, RouteEvent
from harnessweaver.core.messages import ToolCall, ToolSpec
from harnessweaver.core.middleware import Registration
from harnessweaver.core.outcomes import Continue, Outcome
from harnessweaver.core.ports import ModelProvider, ToolBackend, ToolDescription
from harnessweaver.core.registry import PluginCatalog
from harnessweaver.core.telemetry import Telemetry
from harnessweaver.core.tools import Risk, SideEffect, ToolInfo, ToolResult
from harnessweaver.harness import Harness
from harnessweaver.modules.models import ScriptedModel, ScriptedReply
from harnessweaver.spec.loader import EffectiveSpec, load_spec, spec_from_documents
from harnessweaver.spec.models import API_VERSION
from harnessweaver.spec.sources import BuiltinProfiles, PluginProfiles, ProfileDirectories

__all__ = [
    "FakeDecider",
    "FakeTool",
    "FakeTools",
    "harness_for_test",
    "output",
    "reply",
    "scripted",
    "text",
    "tool_call",
]


# --- scripted replies ----------------------------------------------------------------------------


def reply(**fields: Any) -> ScriptedReply:
    """A scripted reply with any of ``text``, ``output``, ``tool_calls``, ``usage``, ``cost_usd``,
    ``model``, ``chunks``, ``finish_reason`` or ``fail``."""
    return ScriptedReply.model_validate(fields)


def text(value: str, **fields: Any) -> ScriptedReply:
    """A reply that answers with ``value``."""
    return reply(text=value, **fields)


def output(value: JsonValue, **fields: Any) -> ScriptedReply:
    """A reply with structured output (also sent as JSON text)."""
    return reply(output=value, **fields)


def tool_call(name: str, /, *, id: str | None = None, **arguments: JsonValue) -> ScriptedReply:
    """A reply that asks for one tool call."""
    return reply(tool_calls=[{"id": id, "name": name, "arguments": arguments}])


def scripted(
    *replies: ScriptedReply | Mapping[str, Any] | str,
    rules: Iterable[Mapping[str, Any]] = (),
    repeat_last: bool = True,
) -> ScriptedModel:
    """A :class:`ScriptedModel` from replies (strings are text replies) and optional rules."""
    return ScriptedModel.of(
        *[
            r.model_dump(exclude_defaults=True)
            if isinstance(r, ScriptedReply)
            else r
            if isinstance(r, str)
            else dict(r)
            for r in replies
        ],
        rules=[dict(r) for r in rules],
        repeat_last=repeat_last,
    )


# --- tools ---------------------------------------------------------------------------------------

type ToolHandler = Callable[[dict[str, JsonValue]], JsonValue | Awaitable[JsonValue]]


@dataclass
class FakeTool:
    """A tool for tests. ``result`` is returned (or called with the arguments); every call
    is kept in ``calls``. ``raises`` makes it fail instead."""

    name: str
    result: JsonValue | ToolHandler = None
    description: str = ""
    input_schema: dict[str, JsonValue] = field(
        default_factory=lambda: dict[str, JsonValue]({"type": "object"})
    )
    side_effect: SideEffect = SideEffect.NONE
    risk: Risk = Risk.LOW
    data_access: tuple[str, ...] = ()
    egress: tuple[str, ...] = ()
    scopes: tuple[str, ...] = ()
    untrusted: bool = True
    raises: Exception | None = None
    calls: list[ToolCall] = field(default_factory=list[ToolCall])

    def describe(self) -> ToolDescription:
        info = ToolInfo(
            name=self.name,
            side_effect=self.side_effect,
            risk=self.risk,
            data_access=self.data_access,
            egress=self.egress,
            scopes=self.scopes,
        )
        return ToolDescription(
            info,
            ToolSpec(name=self.name, description=self.description, input_schema=self.input_schema),
        )

    async def run(self, call: ToolCall) -> ToolResult:
        self.calls.append(call)
        if self.raises is not None:
            raise self.raises
        value: Any = self.result
        if callable(value):
            value = value(dict(call.arguments))
            if inspect.isawaitable(value):
                value = await value
        return ToolResult(call_id=call.id, output=value, untrusted=self.untrusted)


class FakeTools:
    """A tool backend made of :class:`FakeTool` objects."""

    def __init__(self, tools: Iterable[FakeTool] = ()) -> None:
        self.tools = {tool.name: tool for tool in tools}

    def describe(self, name: str) -> ToolDescription | None:
        tool = self.tools.get(name)
        return tool.describe() if tool is not None else None

    async def execute(self, call: ToolCall, env: Envelope) -> ToolResult:
        return await self.tools[call.name].run(call)

    def __getitem__(self, name: str) -> FakeTool:
        return self.tools[name]


# --- routing -------------------------------------------------------------------------------------


class FakeDecider:
    """A routing stage that always gives the same answer; requests are kept in ``requests``.

    With no ``choice`` it abstains. With a ``confidence`` the decision is probabilistic.
    """

    def __init__(
        self,
        choice: str | None = None,
        *,
        confidence: float | None = None,
        reason: str = "fake decider",
    ) -> None:
        self.choice = choice
        self.confidence = confidence
        self.reason = reason
        self.requests: list[DecisionRequest] = []

    async def __call__(self, request: DecisionRequest) -> Decision:
        self.requests.append(request)
        if self.choice is None:
            return Decision.abstain(reason=self.reason)
        if self.confidence is not None:
            return Decision.probabilistic(self.choice, self.confidence, reason=self.reason)
        return Decision(
            kind=DecisionKind.EXACT,
            choice=self.choice,
            confidence=1.0,
            reason=self.reason,
            stage="fake",
        )

    def registration(self, router: str) -> Registration:
        """Middleware that answers ``route.decide`` for ``router``."""

        async def answer(event: RouteEvent, env: Envelope) -> Outcome | None:
            if event.request.router != router or event.decision is not None:
                return None
            return Continue(
                modified=event.model_copy(update={"decision": await self(event.request)})
            )

        return Registration(
            name=f"fake_decider[{router}]",
            handler=answer,
            hooks=frozenset({HookPoint.ROUTE_DECIDE}),
            band=Band.APP,
            fail_mode="closed",
        )


# --- harnesses -----------------------------------------------------------------------------------


def _document(spec: Mapping[str, Any]) -> dict[str, Any]:
    document = {"apiVersion": API_VERSION, "kind": "Harness", "metadata": {"name": "test"}}
    document.update(spec)
    return document


def harness_for_test(
    spec: Mapping[str, Any] | str | Path | EffectiveSpec | None = None,
    *,
    model: ModelProvider | None = None,
    tools: Iterable[FakeTool] | ToolBackend = (),
    deciders: Mapping[str, FakeDecider] | None = None,
    clock: Clock | None = None,
    catalog: PluginCatalog | None = None,
    telemetry: Telemetry | None = None,
) -> Harness:
    """A harness for a test: offline, on a fake clock, with fakes where you give them.

    Args:
        spec: A ``harness.yaml`` path, a spec document as a dict (``apiVersion``,
            ``kind`` and ``metadata`` may be left out), or a loaded spec.
        model: Replaces ``models.provider``, usually a :func:`scripted` model.
        tools: Fake tools, or any tool backend.
        deciders: Fake routing answers by router name.
        clock: Defaults to a :class:`FakeClock`.
        catalog: Where plugins are found; defaults to the installed ones.
        telemetry: Spans and metrics go here (for example an in-memory SDK).

    Raises:
        SpecError: For an invalid spec, as ``Harness.load`` would.
    """
    catalog = catalog or PluginCatalog.default()
    if isinstance(spec, EffectiveSpec):
        effective = spec
    elif isinstance(spec, str | Path):
        effective = load_spec(spec, catalog=catalog)
    else:
        effective = spec_from_documents(
            _document(spec or {}),
            resolvers=[BuiltinProfiles(), PluginProfiles(catalog), ProfileDirectories([])],
        )
    backend = tools if not isinstance(tools, Iterable) else FakeTools(tools)
    harness = Harness.from_spec(
        effective,
        clock=clock or FakeClock(),
        tools=backend,
        catalog=catalog,
        telemetry=telemetry,
        model=model,
    )
    for router, decider in (deciders or {}).items():
        harness._bus.add(decider.registration(router))
    return harness
