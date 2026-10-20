"""HarnessWeaver plugin for Pydantic AI.

Contributes the ``pydantic_ai.agent`` runner, which runs a task with a Pydantic AI
agent, and an adapter for ``harness.wrap(agent)``, which governs an app's
existing one. Both govern the agent through
:class:`harnessweaver_pydantic_ai.capability.HarnessCapability`.

Importing this module imports nothing from ``pydantic_ai``; it loads on first
use (RULES S8).
"""

from importlib.metadata import version as _version

import harnessweaver as hw
from harnessweaver_pydantic_ai.adapter import AgentAdapter
from harnessweaver_pydantic_ai.runner import AgentRunner, AgentRunnerConfig

__version__: str = _version("harnessweaver-pydantic-ai")

plugin = hw.Plugin(
    namespace="pydantic_ai",
    version=__version__,
    runners=[AgentRunner],
    adapters=[AgentAdapter],
    description="The pydantic_ai.agent runner and the wrap() adapter for Pydantic AI agents.",
)

__all__ = ["AgentAdapter", "AgentRunner", "AgentRunnerConfig", "__version__", "plugin"]
