"""Comment-preserving reads and writes of the YAML files the CLI edits (ruamel.yaml, ADR-0016).

The spec loader reads YAML 1.2 with PyYAML (ADR-0017). Editing commands
(``add guard``, ``add tool``, ``tools pin``) use ruamel.yaml's round-trip mode
instead, so the comments, key order and flow style a person wrote survive the
edit. ruamel.yaml reads YAML 1.2 too, so both see the same values.
"""

import io
from pathlib import Path
from typing import Any

from ruamel.yaml import YAML
from ruamel.yaml.comments import CommentedMap

__all__ = ["dump", "flow", "read", "write"]


def _yaml() -> YAML:
    yaml = YAML()  # round-trip mode: comments, order and quoting are kept
    yaml.preserve_quotes = True
    yaml.width = 4096  # never re-wrap a long line someone wrote on purpose
    # The repository's style: list items indented two spaces under their key.
    yaml.indent(mapping=2, sequence=4, offset=2)
    return yaml


def read(path: Path) -> Any:
    """The document at ``path``, as ruamel's comment-keeping maps and lists."""
    return _yaml().load(path.read_text(encoding="utf-8"))


def dump(document: Any) -> str:
    """``document`` as YAML text, with its comments."""
    out = io.StringIO()
    _yaml().dump(document, out)
    return out.getvalue()


def write(path: Path, document: Any) -> None:
    """Write ``document`` to ``path``, comments included."""
    path.write_text(dump(document), encoding="utf-8")


def flow(**items: Any) -> CommentedMap:
    """A map written on one line, ``{ id: x, use: y }``, as spec list items usually are."""
    found = CommentedMap(items)
    found.fa.set_flow_style()
    return found
