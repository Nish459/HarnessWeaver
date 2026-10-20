"""Offline samples for the conformance suite (T5): no network, no keys (R14, S7)."""

from typing import Any

from pydantic_ai import Agent
from pydantic_ai.messages import ModelMessage, ModelResponse, TextPart
from pydantic_ai.models.function import AgentInfo, FunctionModel

from harnessweaver.testing import AdapterSample

__all__ = ["adapter_sample", "agent"]

agent: Agent[None, str] = Agent(name="conformance")
"""The runner's sample: it has no model, so the harness's model answers."""


def _answer(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
    return ModelResponse(parts=[TextPart("hello")])


def adapter_sample() -> AdapterSample:
    """An agent on a local function model, and one run through the wrapped agent."""
    target = Agent(FunctionModel(_answer), name="conformance")

    async def call(wrapped: Any) -> Any:
        return await wrapped.run("hello")

    return AdapterSample(target, call)
