"""Layered merging of spec documents, with provenance, locks and bounds (DESIGNS No. 11).

The rules, which the ``merge`` fixtures pin down for every language:

* Layers merge in order: defaults, built-in profiles, org profiles, the app
  spec, then an environment overlay.
* Scalars and plain lists: the later layer wins. Maps merge key by key.
* Keyed lists (guardrail stages, middleware, routing cascades, rule lists)
  merge by ``id``: an item with a known id updates that item in place, new
  items are appended, and earlier items keep their position. Items without an
  id are appended and get an id ``<use>#<n>`` after merging (``rule#<n>`` in
  rule lists, ``item#<n>`` for other items without a ``use``), skipping ids
  already taken.
* ``null`` can unset a scalar, but can't remove a map or a keyed list.
* A lock declared by a profile covers that path and everything under it for
  all later layers. Changing a locked value is a ``LockViolation`` (R1);
  restating the same value is allowed.
* Bounds declared by profiles accumulate and are checked on the merged
  result. A value out of bounds is a ``BoundViolation``, never clamped (R10).
  Bounds on ``budgets.per_run.<field>`` also apply to every task's budget.
"""

from harnessweaver.spec.merge.bounds import check_bounds
from harnessweaver.spec.merge.layers import (
    KEYED_LISTS,
    Bound,
    Layer,
    LayerKind,
    Lock,
    Merged,
    Provenance,
)
from harnessweaver.spec.merge.merger import merge_layers

__all__ = [
    "KEYED_LISTS",
    "Bound",
    "Layer",
    "LayerKind",
    "Lock",
    "Merged",
    "Provenance",
    "check_bounds",
    "merge_layers",
]
