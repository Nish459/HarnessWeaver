"""The plugin contract: ``hw.Plugin`` and the decorators that declare contributions.

A plugin is defined by its design, not its name (DESIGNS No. 13, ADR-0015). Any
importable module that exposes an :class:`Plugin` object is a plugin, found
through the ``harnessweaver.plugins`` entry-point group or ``plugins.local``.
First-party, third-party and built-in contributions all use this contract.

Declaring something registers nothing. Decorators only attach metadata, and a
``Plugin`` object is a plain description; a harness's registry imports and
registers a plugin only when its effective spec references the plugin's
namespace (S8).
"""

from harnessweaver.core.plugins.decorators import (
    AdapterInfo,
    ProviderInfo,
    RunnerInfo,
    adapter,
    adapter_info,
    decider,
    provider,
    provider_info,
    runner,
    runner_info,
)
from harnessweaver.core.plugins.names import (
    BUILTIN_NAMESPACE,
    CONTRACT_VERSION,
    ENTRY_POINT_GROUP,
    LATENCY_CLASSES,
    PORTS,
    RESERVED_NAMESPACES,
    namespace_of,
    qualify,
)
from harnessweaver.core.plugins.plugin import Contribution, Plugin, as_plugin, check_owned

__all__ = [
    "BUILTIN_NAMESPACE",
    "CONTRACT_VERSION",
    "ENTRY_POINT_GROUP",
    "LATENCY_CLASSES",
    "PORTS",
    "RESERVED_NAMESPACES",
    "AdapterInfo",
    "Contribution",
    "Plugin",
    "ProviderInfo",
    "RunnerInfo",
    "adapter",
    "adapter_info",
    "as_plugin",
    "check_owned",
    "decider",
    "namespace_of",
    "provider",
    "provider_info",
    "qualify",
    "runner",
    "runner_info",
]
