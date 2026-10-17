"""HarnessWeaver plugin for OpenAI-compatible models.

Contributes an openai.chat model provider for any OpenAI-compatible endpoint
(LiteLLM Proxy, OpenAI, vLLM, Ollama) and an adapter for
harness.instrument(OpenAI client).
"""

from importlib.metadata import version as _version

__version__: str = _version("harnessweaver-openai")

__all__ = ["__version__"]
