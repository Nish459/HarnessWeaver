"""Importing app code named in a spec, such as ``"app.flows:answer"``."""

import importlib
from typing import Any

from harnessweaver.core.errors import SpecError

__all__ = ["import_object"]


def import_object(path: str, what: str) -> Any:
    """Import ``package.module:name`` (``name`` may be dotted).

    Raises:
        SpecError: If the path is malformed or can't be imported.
    """
    module_name, sep, attribute = path.partition(":")
    if not sep or not module_name or not attribute:
        raise SpecError(f"{what}: {path!r} must look like 'package.module:name'")
    try:
        value: Any = importlib.import_module(module_name)
        for part in attribute.split("."):
            value = getattr(value, part)
    except (ImportError, AttributeError) as exc:
        raise SpecError(f"{what}: can't import {path!r} ({type(exc).__name__})") from exc
    return value
