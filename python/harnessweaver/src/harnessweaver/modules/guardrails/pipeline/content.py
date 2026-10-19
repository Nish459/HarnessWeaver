"""Reading the strings a stage checks out of a hook payload, and putting them back."""

from collections.abc import Callable, Sequence
from typing import Any

from pydantic import JsonValue

from harnessweaver.core.hooks import (
    InputEvent,
    OutputEvent,
    StreamChunkEvent,
    ToolResultEvent,
)
from harnessweaver.modules.guardrails.pipeline.guards import Stage

__all__ = ["content_of"]

type Path = tuple[str | int, ...]


def _leaves(value: JsonValue, path: Path = ()) -> list[tuple[Path, str]]:
    if isinstance(value, str):
        return [(path, value)]
    if isinstance(value, list):
        return [leaf for i, item in enumerate(value) for leaf in _leaves(item, (*path, i))]
    if isinstance(value, dict):
        return [leaf for key, item in value.items() for leaf in _leaves(item, (*path, key))]
    return []


def _replace(value: JsonValue, changes: dict[Path, str], path: Path = ()) -> JsonValue:
    if path in changes:
        return changes[path]
    if isinstance(value, list):
        return [_replace(item, changes, (*path, i)) for i, item in enumerate(value)]
    if isinstance(value, dict):
        return {key: _replace(item, changes, (*path, key)) for key, item in value.items()}
    return value


def content_of(stage: Stage, event: Any) -> tuple[list[str], Callable[[Sequence[str]], Any]]:
    """The texts a stage checks, and how to rebuild the event from redacted texts."""
    if stage == "stream":
        chunk_event: StreamChunkEvent = event

        def rebuild_chunk(texts: Sequence[str]) -> Any:
            chunk = chunk_event.chunk.model_copy(update={"delta": texts[0]})
            return chunk_event.model_copy(update={"chunk": chunk})

        return [chunk_event.chunk.delta], rebuild_chunk
    if stage == "tool_result":
        result_event: ToolResultEvent = event
        root: JsonValue = result_event.result.output

        def wrap(value: JsonValue) -> Any:
            result = result_event.result.model_copy(update={"output": value})
            return result_event.model_copy(update={"result": result})

    elif stage == "input":
        input_event: InputEvent = event
        root = input_event.input

        def wrap(value: JsonValue) -> Any:
            return input_event.model_copy(update={"input": value})

    else:
        output_event: OutputEvent = event
        root = output_event.output

        def wrap(value: JsonValue) -> Any:
            return output_event.model_copy(update={"output": value})

    leaves = _leaves(root)
    paths = [path for path, _ in leaves]

    def rebuild(texts: Sequence[str]) -> Any:
        return wrap(_replace(root, dict(zip(paths, texts, strict=True))))

    return [text for _, text in leaves], rebuild
