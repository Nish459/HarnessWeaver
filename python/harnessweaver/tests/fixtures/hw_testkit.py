"""A plugin for the runtime tests, loaded through ``plugins.local: [hw_testkit]``.

It is a plugin like any other: a ``Plugin`` object with providers, middleware
and app handlers, using only the public extension surface. Tests read what it
saw from :data:`RECORDER`, which the ``testkit`` fixture resets.
"""

from collections.abc import AsyncIterator
from typing import Any, Literal

import anyio
from hw_recorder import RECORDER
from hw_recorder import Recorder as Recorder
from hw_testkit_tools import Careful, EchoSandbox, Explodes
from hw_testkit_tools import lookup_order as lookup_order  # manifests name hw_testkit:<handler>
from hw_testkit_tools import refund_payment as refund_payment
from hw_testkit_tools import send_email as send_email
from pydantic import BaseModel, ConfigDict, Field, JsonValue

import harnessweaver as hw
from harnessweaver.ports import ToolDescription

# --- a scripted model provider -----------------------------------------------------------------


class Reply(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str = ""
    output: JsonValue = None
    tool_calls: list[hw.ToolCall] = []
    usage: hw.Usage = hw.Usage(input_tokens=10, output_tokens=5)
    cost_usd: float | None = None
    model: str | None = None
    chunks: list[str] | None = None
    wait: bool = False
    fail: bool = False


class ScriptConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    replies: list[Reply] = Field(min_length=1)
    after_tool: Reply | None = Field(
        default=None, description="The reply whenever the last message is a tool result."
    )


@hw.provider(port="ModelProvider", name="scripted", config=ScriptConfig, deterministic=True)
class ScriptedProvider:
    """Answers with the next reply in the script; repeats the last one."""

    def __init__(self, config: ScriptConfig) -> None:
        self.replies = config.replies
        self.after_tool = config.after_tool
        self.index = 0

    def _next(self, request: hw.ModelRequest) -> Reply:
        RECORDER.requests.append(request)
        last = request.messages[-1] if request.messages else None
        if self.after_tool is not None and last is not None and last.role is hw.Role.TOOL:
            return self.after_tool
        reply = self.replies[min(self.index, len(self.replies) - 1)]
        self.index += 1
        return reply

    @staticmethod
    def _response(reply: Reply, request: hw.ModelRequest) -> hw.ModelResponse:
        return hw.ModelResponse(
            model=reply.model or request.model,
            text=reply.text,
            output=reply.output,
            tool_calls=tuple(reply.tool_calls),
            usage=reply.usage,
            cost_usd=reply.cost_usd,
        )

    async def generate(self, request: hw.ModelRequest, env: hw.Envelope) -> hw.ModelResponse:
        RECORDER.envelopes.append(env)
        reply = self._next(request)
        if reply.wait:
            await anyio.Event().wait()
        if reply.fail:
            raise ConnectionError("upstream is down")
        return self._response(reply, request)

    async def stream(
        self, request: hw.ModelRequest, env: hw.Envelope
    ) -> AsyncIterator[hw.StreamChunk | hw.ModelResponse]:
        reply = self._next(request)
        for index, delta in enumerate(reply.chunks or [reply.text]):
            yield hw.StreamChunk(index=index, delta=delta)
        yield self._response(reply, request)


# --- middleware ----------------------------------------------------------------------------------


@hw.middleware(hooks=list(hw.HookPoint), fail_mode="closed")
async def audit(event: Any, env: hw.Envelope) -> hw.Outcome | None:
    """Records every hook it sees."""
    RECORDER.hooks.append(event.hook)
    return None


@hw.middleware(hooks=["input.before"], fail_mode="open")
async def flaky(event: Any, env: hw.Envelope) -> hw.Outcome | None:
    raise RuntimeError("flaky middleware")


class Rule(BaseModel):
    model_config = ConfigDict(extra="forbid")

    hook: str
    outcome: Literal["continue", "modify", "retry", "escalate", "suspend", "block", "raise", "wait"]
    reason: str = "scripted"
    code: str = "scripted"
    approver_role: str | None = None
    tool: str | None = None
    value: JsonValue = None
    times: int | None = None


class ScriptMiddlewareConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rules: list[Rule]


@hw.middleware(hooks=list(hw.HookPoint), fail_mode="closed", config=ScriptMiddlewareConfig)
class Script:
    """Answers hook events as its rules say. Approved events always continue."""

    def __init__(self, config: ScriptMiddlewareConfig) -> None:
        self.rules = config.rules
        self.used: dict[int, int] = {}

    def _modify(self, event: Any, value: JsonValue) -> Any:
        if isinstance(event, hw.InputEvent):
            return event.model_copy(update={"input": value})
        if isinstance(event, hw.OutputEvent):
            return event.model_copy(update={"output": value})
        if isinstance(event, hw.ToolCallEvent):
            assert isinstance(value, dict)
            return event.model_copy(
                update={"call": event.call.model_copy(update={"arguments": value})}
            )
        if isinstance(event, hw.StreamChunkEvent):
            return event.model_copy(
                update={"chunk": event.chunk.model_copy(update={"delta": value})}
            )
        if isinstance(event, hw.ModelRequestEvent):
            return event.model_copy(
                update={"request": event.request.model_copy(update={"alias": value})}
            )
        if isinstance(event, hw.RouteEvent):
            assert isinstance(value, str)
            return event.model_copy(
                update={"decision": hw.Decision.exact(value, reason="scripted")}
            )
        if isinstance(event, hw.ContextEvent):
            return event.model_copy(
                update={"items": tuple(i for i in event.items if i.id != value)}
            )
        if isinstance(event, hw.ToolResultEvent):
            return event.model_copy(
                update={"result": event.result.model_copy(update={"output": value})}
            )
        raise AssertionError(f"can't modify {event.hook}")

    async def __call__(self, event: Any, env: hw.Envelope) -> hw.Outcome | None:
        if getattr(event, "approval", None) is not None:
            return None
        for index, rule in enumerate(self.rules):
            if rule.hook != event.hook:
                continue
            if (
                rule.tool is not None
                and getattr(getattr(event, "call", None), "name", None) != rule.tool
            ):
                continue
            if rule.times is not None and self.used.get(index, 0) >= rule.times:
                continue
            self.used[index] = self.used.get(index, 0) + 1
            match rule.outcome:
                case "continue":
                    return hw.Continue(note=rule.reason)
                case "modify":
                    return hw.Continue(modified=self._modify(event, rule.value))
                case "retry":
                    return hw.Retry(reason=rule.reason)
                case "escalate":
                    return hw.Escalate(reason=rule.reason)
                case "suspend":
                    return hw.Suspend(reason=rule.reason, approver_role=rule.approver_role)
                case "block":
                    return hw.Block(reason=rule.reason, code=rule.code)
                case "raise":
                    raise RuntimeError("scripted failure")
                case "wait":
                    await anyio.Event().wait()
        return None


# --- tools ---------------------------------------------------------------------------------------


def _tool(name: str, description: str, **spec: Any) -> ToolDescription:
    document = {"metadata": {"name": name}, "spec": {"description": description, **spec}}
    return ToolDescription.from_manifest(hw.ToolManifest.model_validate(document))


class FakeTools:
    """A tool backend with three tools: lookup (read), refund (writes) and crash."""

    def __init__(self) -> None:
        self.tools = {
            "lookup": _tool(
                "lookup", "Look up a customer", side_effect="read", data_access=["pii:customer"]
            ),
            "refund": _tool(
                "refund", "Refund a payment", side_effect="write_external", risk="high"
            ),
            "crash": _tool("crash", "Always fails"),
        }

    def describe(self, name: str) -> ToolDescription | None:
        return self.tools.get(name)

    async def execute(self, call: hw.ToolCall, env: hw.Envelope) -> hw.ToolResult:
        RECORDER.tool_calls.append(call)
        if call.name == "crash":
            raise ValueError("secret detail that must not leak")
        if call.name == "refund":
            return hw.ToolResult(call_id=call.id, output={"refunded": call.arguments.get("amount")})
        return hw.ToolResult(call_id=call.id, output={"customer": "alice", "tier": "gold"})


# --- app handlers for the session and workflow runners ----------------------------------------


class Ticket(BaseModel):
    text: str
    priority: int = 1


class Summary(BaseModel):
    title: str
    words: int


async def answer(s: hw.Session, input: Any) -> Any:
    """A session-runner handler: routes, calls a tool and generates."""
    RECORDER.notes.append(("answer", input))
    route = await s.decide("intent", text=str(input), options=["billing", "other"], default="other")
    customer = await s.tool("lookup", id="c-1")
    text = await s.generate(prompt="reply@1", route=route.choice, customer=customer)
    return {"route": route.choice, "text": text}


async def refund_flow(s: hw.Session, input: Any) -> Any:
    RECORDER.notes.append(("refund_flow", input))
    result = await s.tool("refund", amount=input["amount"])
    return {"done": result}


async def extract(s: hw.Session, inputs: dict[str, Any]) -> Any:
    RECORDER.notes.append(("extract", inputs["input"]))
    return {"text": str(inputs["input"]).upper()}


async def classify(s: hw.Session, inputs: dict[str, Any]) -> Any:
    RECORDER.notes.append(("classify", inputs["extract"]))
    return "billing" if "REFUND" in inputs["extract"]["text"] else "other"


async def summarize(s: hw.Session, inputs: dict[str, Any]) -> Any:
    RECORDER.notes.append(("summarize", inputs["extract"]))
    return await s.generate(prompt="reply@1", route="summary", customer=inputs["extract"])


async def approve_refund(s: hw.Session, inputs: dict[str, Any]) -> Any:
    RECORDER.notes.append(("approve_refund", inputs["classify"]))
    return await s.tool("refund", amount=5)


async def draft(s: hw.Session, inputs: dict[str, Any]) -> Any:
    RECORDER.notes.append(("draft", inputs.get("round"), inputs.get("feedback")))
    return f"draft {inputs.get('round')} for {inputs['classify']}"


async def review(s: hw.Session, output: Any) -> bool | str:
    RECORDER.notes.append(("review", output))
    return True if output.startswith("draft 2") else "make it better"


async def never_happy(s: hw.Session, output: Any) -> bool | str:
    return False


async def explode(s: hw.Session, inputs: dict[str, Any]) -> Any:
    raise KeyError("app bug")


async def full_tour(s: hw.Session, input: Any) -> Any:
    """Touches every governed operation, so a run fires every hook point."""
    route = await s.decide("intent", text="refund please", options=["billing", "other"])
    items = await s.context("kb").check(
        [hw.ContextItem(id="d1", content="Refunds take 5 days", source="kb")], query="refund"
    )
    refund = await s.tool("refund", amount=input["amount"])
    text = await s.generate(prompt="reply@1", stream=True, route=route.choice, customer=len(items))
    return {"route": route.choice, "refund": refund, "text": text}


@hw.runner(
    "partial", reaches=["run.start", "input.before", "model.before", "model.after", "run.end"]
)
class PartialRunner:
    """A runner that can't reach tool hooks, for reachability tests (R4)."""

    async def execute(self, ctx: hw.RunContext, input: Any, resume: Any) -> Any:
        return input


plugin = hw.Plugin(
    namespace="testkit",
    version="0.1.0",
    providers=[ScriptedProvider, EchoSandbox, Careful, Explodes],
    middleware=[audit, flaky, Script],
    runners=[PartialRunner],
    profiles={"strict": "testkit_profiles/strict.yaml"},
)
