"""The ``context`` module: retrieval and memory that respect ACLs (DESIGNS No. 21).

``context.<source>`` names a ``ContextProvider`` (``passthrough``, ``memory``, or a
plugin's). What a source returns, or what the app passes in, is governed before
the ``context.after`` middleware sees it: ACLs re-checked, provenance labelled,
caps enforced, every drop traced. ``memory`` names the ``Memory`` provider behind
``s.memory``, namespaced per tenant, principal and task.
"""

from harnessweaver.modules.context.memory import MemoryStore
from harnessweaver.modules.context.providers import (
    Document,
    MemoryContext,
    MemoryContextConfig,
    PassthroughContext,
)
from harnessweaver.modules.context.sources import ContextSources

__all__ = [
    "ContextSources",
    "Document",
    "MemoryContext",
    "MemoryContextConfig",
    "MemoryStore",
    "PassthroughContext",
]
