"""Agents, tools and an audit plugin for the plugin's tests: offline, fake data (R14, S7)."""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel
from pydantic_ai import Agent, CallDeferred, RunContext, Tool
from pydantic_ai.messages import ModelMessage, ModelResponse, TextPart, ToolCallPart
from pydantic_ai.models.function import AgentInfo, FunctionModel

import harnessweaver as hw

RAN: list[tuple[str, dict[str, Any]]] = []
"""Every agent tool that ran, with its arguments."""
SEEN: list[tuple[str, str]] = []
"""Every hook the audit middleware saw, with the run's id."""
ASKED: list[list[ModelMessage]] = []
"""What each function model was asked."""
INSTRUCTED: list[str | None] = []
"""The instructions each function model was given."""


def reset() -> None:
    RAN.clear()
    SEEN.clear()
    ASKED.clear()
    INSTRUCTED.clear()


class Answer(BaseModel):
    category: str


support: Agent[None, Answer] = Agent(
    output_type=Answer, instructions="Classify the message.", name="support"
)


def lookup_order(order_id: str) -> dict[str, str]:
    """Look up an order."""
    RAN.append(("lookup_order", {"order_id": order_id}))
    return {"order": order_id, "status": "shipped"}


def cancel_order(order_id: str) -> str:
    """Cancel an order."""
    RAN.append(("cancel_order", {"order_id": order_id}))
    return "cancelled"


def courier(order_id: str) -> str:
    """Hand an order to the courier, outside the agent."""
    raise CallDeferred


helper: Agent[None, str] = Agent(
    name="helper",
    tools=[lookup_order, Tool(cancel_order, requires_approval=True), courier],
)


@dataclass
class Shop:
    name: str


async def make_shop(session: hw.Session, input: Any) -> Shop:
    return Shop(name=f"shop for {session.envelope.tenant}")


shop_agent: Agent[Shop, str] = Agent(deps_type=Shop, name="shop")


@shop_agent.tool
def shop_name(ctx: RunContext[Shop]) -> str:
    """The shop's name."""
    RAN.append(("shop_name", {}))
    return ctx.deps.name


not_an_agent = object()

type Reply = ModelResponse | Callable[[list[ModelMessage], AgentInfo], ModelResponse]


def model(*replies: Reply) -> FunctionModel:
    """A function model that answers with ``replies`` in order, repeating the last one."""
    used = [0]

    def answer(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        ASKED.append(list(messages))
        INSTRUCTED.append(info.instructions)
        reply = replies[min(used[0], len(replies) - 1)]
        used[0] += 1
        return reply(messages, info) if callable(reply) else reply

    return FunctionModel(answer)


def text(content: str) -> ModelResponse:
    return ModelResponse(parts=[TextPart(content)])


def calls(*calls: tuple[str, dict[str, Any]]) -> ModelResponse:
    return ModelResponse(parts=[ToolCallPart(name, args) for name, args in calls])


@hw.middleware(hooks=list(hw.HookPoint), band="app", fail_mode="closed")
async def audit(event: Any, env: hw.Envelope) -> None:
    SEEN.append((str(hw.HookPoint(event.hook).value), env.run_id))


@hw.middleware(hooks=["output.before"], band="app", fail_mode="closed")
async def review_answers(event: hw.OutputEvent, env: hw.Envelope) -> hw.Outcome | None:
    """Every answer waits for a reviewer once."""
    if event.approval is None:
        return hw.Suspend(reason="answers are reviewed", approver_role="finance")
    return None


@hw.middleware(hooks=["model.before"], band="app", fail_mode="closed")
async def hide_codes(event: hw.ModelRequestEvent, env: hw.Envelope) -> hw.Outcome | None:
    """Replaces the word 'secret' in what models are asked."""
    messages = tuple(
        m.model_copy(update={"content": m.content.replace("secret", "[hidden]")})
        for m in event.request.messages
    )
    if messages == event.request.messages:
        return None
    request = event.request.model_copy(update={"messages": messages})
    return hw.Continue(modified=event.model_copy(update={"request": request}))


plugin = hw.Plugin(
    namespace="pai_test", version="0.1.0", middleware=[audit, review_answers, hide_codes]
)


def spec(**sections: Any) -> dict[str, Any]:
    """A spec that loads this module's plugin and audits every hook."""
    return {
        "plugins": {"local": ["pai_agents"]},
        "middleware": [{"use": "pai_test.audit"}],
        **sections,
    }


def runner(agent: str = "support", **settings: Any) -> dict[str, Any]:
    return {"use": "pydantic_ai.agent", "agent": f"pai_agents:{agent}", **settings}


def hooks(run_id: str | None = None) -> list[str]:
    """The hooks the audit saw, first time each, for one run or all."""
    seen: list[str] = []
    for hook, run in SEEN:
        if (run_id is None or run == run_id) and hook not in seen:
            seen.append(hook)
    return seen


async def ask_agent(session: hw.Session, input: Any) -> Any:
    """A session-runner handler that runs a wrapped agent inside the harness's run."""
    harness: Any = session.run_context.harness
    replies = (calls(("lookup_order", {"order_id": "7"})), text("shipped"))
    agent = Agent(model(*replies), tools=[lookup_order])
    return (await harness.wrap(agent).run(str(input))).output
