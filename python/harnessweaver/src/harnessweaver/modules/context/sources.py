"""Governing context: ACL re-checks, provenance labels and caps (DESIGNS No. 21, ADR-0030).

Every item that reaches a run, fetched from a provider or passed in by the app,
goes through :meth:`ContextSources.govern` before the ``context.after``
middleware sees it:

1. **ACL re-check.** An item whose ACL excludes the run's tenant or principal is
   dropped, even if its provider returned it (defense in depth); with
   ``require_acl``, so is an item with no ACL.
2. **Labels.** The item's ``source`` becomes the source's name, and it is
   untrusted unless the source is ``label: trusted`` (S3).
3. **Caps.** Items past ``max_items``, then past ``max_tokens`` (one token per
   four characters), are dropped in the order they came.

Each drop is a ``harness.context`` trace note naming the item's id, never its
content (R9, R13).
"""

import math
from collections.abc import Mapping, Sequence

from harnessweaver.core.errors import SpecError
from harnessweaver.core.hooks import HookPoint
from harnessweaver.core.outcomes import OutcomeKind
from harnessweaver.core.ports import ContextProvider, GovernedRun
from harnessweaver.core.retrieval import ContextItem
from harnessweaver.spec.models import ContextSourceSpec

__all__ = ["ContextSources"]


class ContextSources:
    """The spec's ``context`` sources, with their providers. One per harness."""

    def __init__(self, sources: Mapping[str, tuple[ContextSourceSpec, ContextProvider]]) -> None:
        self.sources = dict(sources)

    async def fetch(
        self, ctx: GovernedRun, source: str, query: str, *, limit: int | None = None
    ) -> list[ContextItem]:
        """Ask the source's provider; the caller governs what comes back.

        Raises:
            SpecError: For a source the spec doesn't name.
        """
        found = self.sources.get(source)
        if found is None:
            names = ", ".join(sorted(self.sources)) or "(none)"
            raise SpecError(f"no context source {source!r}; the spec has {names}")
        spec, provider = found
        limits = [n for n in (limit, spec.max_items) if n is not None]
        return list(
            await provider.fetch(query, ctx.envelope, limit=min(limits) if limits else None)
        )

    def govern(
        self, ctx: GovernedRun, source: str, items: Sequence[ContextItem]
    ) -> tuple[ContextItem, ...]:
        """ACL re-check, labels and caps, in that order; every drop traced."""
        spec = self.sources[source][0] if source in self.sources else None
        envelope = ctx.envelope

        def drop(item: ContextItem, code: str, why: str) -> None:
            ctx.trace.note(
                "harness.context",
                f"dropped {item.id} from {source}: {why}",
                hook=HookPoint.CONTEXT_AFTER,
                code=code,
                outcome=OutcomeKind.BLOCK,
                details={"source": source, "item": item.id},
            )

        kept: list[ContextItem] = []
        for item in items:
            if item.acl is not None and not item.acl.allows(envelope.tenant, envelope.principal):
                drop(item, "context_acl", "its ACL excludes this run")
            elif spec is not None and spec.require_acl and item.acl is None:
                drop(item, "context_acl", "it has no ACL and the source requires one")
            else:
                untrusted = spec.label == "untrusted" if spec is not None else item.untrusted
                kept.append(item.model_copy(update={"source": source, "untrusted": untrusted}))
        if spec is None:
            return tuple(kept)
        capped: list[ContextItem] = []
        tokens = 0
        for item in kept:
            size = math.ceil(len(item.content) / 4)
            if spec.max_items is not None and len(capped) >= spec.max_items:
                drop(item, "context_cap", f"over max_items ({spec.max_items})")
            elif spec.max_tokens is not None and tokens + size > spec.max_tokens:
                drop(item, "context_cap", f"over max_tokens ({spec.max_tokens})")
            else:
                capped.append(item)
                tokens += size
        return tuple(capped)
