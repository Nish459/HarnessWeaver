"""Plugin discovery (:class:`PluginCatalog`) and per-harness registration (:class:`Registry`).

The loading lifecycle (DESIGNS No. 13):

1. **Discover** entry-point metadata. Nothing is imported.
2. **Resolve** the namespaces a spec references. A name's namespace is the text
   before its first dot; reserved namespaces belong to the built-in plugin.
3. **Allow**: a namespace outside the org's ``plugins.allow`` fails (S8).
4. **Import** only the referenced plugins, and check their contract range (V5).
5. **Register** their contributions in this harness's registry (C4).

Every failure is a :class:`~harnessweaver.errors.SpecError` subclass raised at
load time, never at run time (R4).
"""

from harnessweaver.core.registry.catalog import (
    LoadedPlugin,
    PluginCatalog,
    PluginSource,
    import_target,
)
from harnessweaver.core.registry.registration import Registry, is_allowed, owner_of

__all__ = [
    "LoadedPlugin",
    "PluginCatalog",
    "PluginSource",
    "Registry",
    "import_target",
    "is_allowed",
    "owner_of",
]
