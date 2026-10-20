"""Example 03 in the Wrap style: an agent the app already has, governed as it is.

    HARNESSWEAVER_ENV=offline uv run python examples/03_refund_agent/wrap.py

The support team's triage agent was written before HarnessWeaver: its own model,
its own ``lookup_order`` tool. One line puts it under the harness. Its model calls
are then traced and budgeted, its tool calls pass the same manifest, policy and
trifecta checks as the Run style's, Acme's guard redacts account numbers from tool
results before the model sees them, and its answers pass the output guards.
"""

import asyncio
import os
from pathlib import Path
from typing import Any

from pydantic_ai import Agent
from pydantic_ai.messages import ModelMessage, ModelResponse, TextPart, ToolCallPart, ToolReturnPart
from pydantic_ai.models import Model
from pydantic_ai.models.function import AgentInfo, FunctionModel
from refunds.tools import lookup_order

import harnessweaver as hw

HERE = Path(__file__).resolve().parent
SPEC = HERE / "harness.yaml"
ORG = HERE.parent / "_org"
SEEN: list[Any] = []
"""What the offline model got back from the tool (tests check the redaction)."""


def live_model() -> Model:
    """The agent's own model: the gateway, with SDK retries off (the gateway retries, R5)."""
    from openai import AsyncOpenAI
    from pydantic_ai.models.openai import OpenAIChatModel
    from pydantic_ai.providers.openai import OpenAIProvider

    client = AsyncOpenAI(
        base_url="http://localhost:4000", api_key=os.environ["LITELLM_API_KEY"], max_retries=0
    )
    return OpenAIChatModel("fast-chat", provider=OpenAIProvider(openai_client=client))


def _offline_answer(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
    """Look the order up first; then answer from what the tool returned."""
    last = messages[-1].parts[-1]
    if isinstance(last, ToolReturnPart):
        SEEN.append(last.content)
        status = last.content.get("status") if isinstance(last.content, dict) else None
        return ModelResponse(parts=[TextPart(f"Order A-1002 was {status}.")])
    return ModelResponse(parts=[ToolCallPart("lookup_order", {"order_id": "A-1002"})])


def existing_agent(model: Model) -> Agent[None, str]:
    """The app's agent as it was before HarnessWeaver: its own model and its own tool."""
    return Agent(model, name="triage", instructions="Answer order questions.", tools=[lookup_order])


async def main() -> str:
    """Wrap the existing agent and ask it one question."""
    harness = hw.load(SPEC, profile_dirs=[ORG])
    offline = os.environ.get("HARNESSWEAVER_ENV") == "offline"
    model = FunctionModel(_offline_answer) if offline else live_model()
    agent = harness.wrap(existing_agent(model), task="refund", principal="casey", tenant="acme")
    result = await agent.run("Where is my order A-1002?")
    print(result.output)
    return result.output


if __name__ == "__main__":
    asyncio.run(main())
