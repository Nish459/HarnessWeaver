"""The agent ``harness.wrap(agent)`` returns (see ``adapter``)."""

from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
from typing import Any

from pydantic_ai.agent import AbstractAgent, WrapperAgent
from pydantic_ai.capabilities import AgentCapability
from pydantic_ai.run import AgentRun

from harnessweaver.adapters import Binding
from harnessweaver_pydantic_ai.capability import HarnessCapability

__all__ = ["GovernedAgent"]


class GovernedAgent(WrapperAgent[Any, Any]):
    """A Pydantic AI agent whose every run the harness governs."""

    def __init__(self, wrapped: AbstractAgent[Any, Any], binding: Binding) -> None:
        super().__init__(wrapped)
        self.binding = binding

    @asynccontextmanager
    async def iter(  # pyright: ignore[reportIncompatibleMethodOverride]
        self,
        user_prompt: Any = None,
        *,
        capabilities: Sequence[AgentCapability[Any]] | None = None,
        **options: Any,
    ) -> AsyncIterator[AgentRun[Any, Any]]:
        # A new capability for each run: it holds that run's state.
        governed = [*(capabilities or ()), HarnessCapability(binding=self.binding)]
        async with self.wrapped.iter(user_prompt, capabilities=governed, **options) as run:
            yield run
