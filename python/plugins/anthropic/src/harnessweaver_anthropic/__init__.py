"""HarnessWeaver plugin for Anthropic models.

Contributes the ``anthropic.messages`` model provider for the Claude Messages API
and an adapter for ``harness.instrument(Anthropic | AsyncAnthropic client)``.

Importing this module imports neither ``anthropic`` nor anything else heavy; the
SDK loads on first use (RULES S8).
"""

from importlib.metadata import version as _version

import harnessweaver as hw
from harnessweaver_anthropic.adapter import AnthropicClientAdapter
from harnessweaver_anthropic.messages import AnthropicMessages, AnthropicMessagesConfig

__version__: str = _version("harnessweaver-anthropic")

plugin = hw.Plugin(
    namespace="anthropic",
    version=__version__,
    providers=[AnthropicMessages],
    adapters=[AnthropicClientAdapter],
    description="Claude models through the Messages API and the instrument() adapter.",
)

__all__ = [
    "AnthropicClientAdapter",
    "AnthropicMessages",
    "AnthropicMessagesConfig",
    "__version__",
    "plugin",
]
