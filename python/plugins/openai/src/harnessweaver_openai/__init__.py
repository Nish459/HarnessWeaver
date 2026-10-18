"""HarnessWeaver plugin for OpenAI-compatible models.

Contributes the ``openai.chat`` model provider for any OpenAI-compatible endpoint
(LiteLLM Proxy, OpenAI, vLLM, Ollama) and an adapter for
``harness.instrument(OpenAI | AsyncOpenAI client)``.

Importing this module imports neither ``openai`` nor anything else heavy; the
SDK loads on first use (RULES S8).
"""

from importlib.metadata import version as _version

import harnessweaver as hw
from harnessweaver_openai.adapter import OpenAIClientAdapter
from harnessweaver_openai.chat import OpenAIChat, OpenAIChatConfig

__version__: str = _version("harnessweaver-openai")

plugin = hw.Plugin(
    namespace="openai",
    version=__version__,
    providers=[OpenAIChat],
    adapters=[OpenAIClientAdapter],
    description="OpenAI-compatible chat models and the instrument() adapter for OpenAI clients.",
)

__all__ = ["OpenAIChat", "OpenAIChatConfig", "OpenAIClientAdapter", "__version__", "plugin"]
