"""Identifiers for runs, approvals and other framework objects."""

import uuid

__all__ = ["new_id"]


def new_id(prefix: str) -> str:
    """Return a new random identifier such as ``run_3f2a...``.

    The prefix makes identifiers self-describing in logs and traces.
    """
    return f"{prefix}_{uuid.uuid4().hex}"
