"""Reading spec files as YAML 1.2 (core schema), the same way in every language.

PyYAML implements YAML 1.1, where ``no`` is ``False``, ``1:30`` is ``90`` and
``2026-01-05`` is a date. JavaScript's ``yaml`` package follows YAML 1.2. To
make a spec mean the same thing everywhere, this loader resolves plain scalars
with the YAML 1.2 core schema only, and rejects duplicate keys instead of
silently keeping the last one (DESIGNS ADR-0017).
"""

import re
from pathlib import Path
from typing import Any

import yaml
from yaml.constructor import ConstructorError
from yaml.nodes import MappingNode, Node

from harnessweaver.core.errors import SpecError

__all__ = ["load_yaml", "load_yaml_file"]


class _CoreSchemaLoader(yaml.SafeLoader):
    """A safe loader with YAML 1.2 core-schema scalars and no duplicate keys."""

    yaml_implicit_resolvers: dict[str, list[tuple[str, re.Pattern[str]]]] = {}  # noqa: RUF012

    def construct_mapping(self, node: Node, deep: bool = False) -> dict[Any, Any]:
        if isinstance(node, MappingNode):
            seen: set[Any] = set()
            for key_node, _ in node.value:
                key = self.construct_object(key_node, deep=deep)  # type: ignore[no-untyped-call]
                if key in seen:
                    raise ConstructorError(
                        None, None, f"duplicate key {key!r}", key_node.start_mark
                    )
                seen.add(key)
        return super().construct_mapping(node, deep=deep)  # type: ignore[no-untyped-call]


def _resolver(tag: str, pattern: str, first: list[str]) -> None:
    _CoreSchemaLoader.add_implicit_resolver(tag, re.compile(pattern, re.X), first)  # pyright: ignore[reportUnknownMemberType]


_resolver("tag:yaml.org,2002:null", r"^(?:~|null|Null|NULL|)$", ["~", "n", "N", ""])
_resolver("tag:yaml.org,2002:bool", r"^(?:true|True|TRUE|false|False|FALSE)$", list("tTfF"))
_resolver(
    "tag:yaml.org,2002:int", r"^(?:[-+]?[0-9]+|0o[0-7]+|0x[0-9a-fA-F]+)$", list("-+0123456789")
)
_resolver(
    "tag:yaml.org,2002:float",
    r"""^(?:[-+]?(?:\.[0-9]+|[0-9]+(?:\.[0-9]*)?)(?:[eE][-+]?[0-9]+)?
        |[-+]?\.(?:inf|Inf|INF)
        |\.(?:nan|NaN|NAN))$""",
    list("-+0123456789."),
)


def _construct_int(loader: yaml.SafeLoader, node: Node) -> int:
    text = str(loader.construct_scalar(node))  # type: ignore[arg-type]
    if text.startswith("0o"):
        return int(text[2:], 8)
    if text.startswith("0x"):
        return int(text[2:], 16)
    return int(text)


_CoreSchemaLoader.add_constructor("tag:yaml.org,2002:int", _construct_int)


def load_yaml(text: str, source: str = "<string>") -> Any:
    """Parse YAML 1.2 text.

    Raises:
        SpecError: If the text isn't valid YAML or repeats a key.
    """
    try:
        return yaml.load(text, Loader=_CoreSchemaLoader)  # a SafeLoader subclass
    except yaml.YAMLError as exc:
        raise SpecError(f"{source}: invalid YAML: {exc}", source=source) from None


def load_yaml_file(path: Path) -> Any:
    """Read and parse a YAML 1.2 file.

    Raises:
        SpecError: If the file can't be read or parsed.
    """
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise SpecError(f"can't read {path}: {exc.strerror}", source=str(path)) from None
    return load_yaml(text, str(path))
