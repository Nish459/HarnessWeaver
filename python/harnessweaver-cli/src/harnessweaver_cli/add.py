"""``harnessweaver add guard`` and ``harnessweaver add tool``: grow a spec without hand-editing it.

Both edit files in place with comments kept (``_yaml``), then load the spec the
way the app would. A guard whose edit doesn't load is taken back out, so a
failed ``add`` leaves the spec as it was.
"""

import inspect
import re
import typing
from pathlib import Path
from typing import Annotated, Any, Literal

import typer
from pydantic import Field, ValidationError, create_model
from ruamel.yaml.comments import CommentedMap, CommentedSeq

from harnessweaver import Harness, Risk, SideEffect, ToolManifest
from harnessweaver.core.errors import HarnessError
from harnessweaver.core.jsonschema import SchemaError, check_schema
from harnessweaver.spec import load_spec
from harnessweaver.spec.yaml import load_yaml
from harnessweaver_cli import _yaml
from harnessweaver_cli._load import fail, spec_path
from harnessweaver_cli.spec import Env, Path_, ProfileDirs

__all__ = ["add_app", "input_schema"]

add_app = typer.Typer(help="Add a guard or a tool to the spec.", no_args_is_help=True)

Stage = Literal["input", "context", "tool_result", "output", "stream"]

_PARAM = re.compile(r"^(\w+)\s*(?:\([^)]*\))?\s*:\s*(.*)$")
"""A docstring ``Args:`` entry: ``name: text`` or ``name (type): text``."""

_IDEMPOTENCY_KEY = "idempotency_key"
"""A native tool's parameter the governor fills in; the model never sees it (DESIGNS No. 17)."""


def _settings(items: list[str]) -> dict[str, Any]:
    """``--set KEY=VALUE`` options as provider settings, each value read as YAML."""
    found: dict[str, Any] = {}
    for item in items:
        key, sep, raw = item.partition("=")
        if not sep or not key:
            raise fail(f"--set {item!r} must look like KEY=VALUE")
        found[key] = load_yaml(raw, f"--set {key}") if raw else ""
    return found


def _check(path: Path, env: str | None, profile_dirs: list[Path]) -> None:
    """Load and build the harness from ``path``, as ``spec validate`` does."""
    Harness.from_spec(load_spec(path, env=env, profile_dirs=profile_dirs))


@add_app.command("guard")
def add_guard(
    use: Annotated[str, typer.Argument(help="The guard provider, such as pii.regex or acme.pii.")],
    path: Path_ = None,
    stage: Annotated[Stage, typer.Option("--stage", help="Where it checks content.")] = "input",
    guard_id: Annotated[
        str | None, typer.Option("--id", help="Its id (default: the provider name with dashes).")
    ] = None,
    action: Annotated[
        str | None, typer.Option("--action", help="What it does when it fires (overrides its own).")
    ] = None,
    settings: Annotated[
        list[str] | None, typer.Option("--set", help="A provider setting, KEY=VALUE; repeatable.")
    ] = None,
    env: Env = None,
    profile_dir: ProfileDirs = None,
) -> None:
    """Add a guard in shadow mode (``mode: log_only``): it records what it would do and
    changes nothing until a reviewed edit promotes it to ``enforce`` (R8)."""
    target = spec_path(path)
    original = target.read_text(encoding="utf-8")
    document = _yaml.read(target)
    if not isinstance(document, CommentedMap):
        raise fail(f"{target} must be a YAML map")
    name = guard_id or use.replace(".", "-")
    guards = document.setdefault("guardrails", CommentedMap()).setdefault(stage, CommentedSeq())
    if any(isinstance(g, dict) and g.get("id") == name for g in guards):
        raise fail(f"guardrails.{stage} already has a guard {name!r}; pick another --id")
    item = _yaml.flow(id=name, use=use, mode="log_only")
    if action is not None:
        item["action"] = action
    item.update(_settings(settings or []))
    guards.append(item)
    _yaml.write(target, document)
    try:
        _check(target, env, profile_dir or [])
    except HarnessError as exc:
        target.write_text(original, encoding="utf-8")  # leave the spec as it was
        raise fail(exc) from None
    typer.echo(f"added guardrails.{stage}[{name}] ({use}) in shadow mode (mode: log_only)")
    typer.echo("  promote it with mode: enforce once the eval shadow report backs it (R8)")


# --- add tool ----------------------------------------------------------------------------------


def _docs(function: Any) -> tuple[str, dict[str, str]]:
    """A function's summary and its parameter descriptions, from a Google-style docstring.

    The summary is the text before the first section header (``Args:``,
    ``Returns:``, ...). Parameter descriptions are the ``name: text`` lines under
    ``Args:``, with indented continuation lines joined on.
    """
    lines = (inspect.getdoc(function) or "").splitlines()
    summary: list[str] = []
    params: dict[str, str] = {}
    section: str | None = None
    current: str | None = None
    for line in lines:
        stripped = line.strip()
        if stripped.endswith(":") and stripped[:-1] in ("Args", "Arguments", "Returns", "Raises"):
            section, current = stripped[:-1], None
            continue
        if section is None:
            summary.append(stripped)
        elif section in ("Args", "Arguments") and stripped:
            # Entries sit one indent under "Args:"; deeper lines continue the last one.
            entry = None if line.startswith("        ") else _PARAM.match(stripped)
            if entry is not None:
                current = str(entry[1])
                params[current] = str(entry[2]).strip()
            elif current is not None:
                params[current] = f"{params[current]} {stripped}".strip()
    return " ".join(s for s in summary if s).strip(), params


def input_schema(function: Any) -> dict[str, Any]:
    """The JSON Schema of a function's parameters, as a tool manifest's ``input_schema``.

    Pydantic builds it from the type hints and defaults; ``idempotency_key``
    is left out because the governor supplies it. Titles are dropped, since
    only the property names and descriptions mean anything to a model.

    Raises:
        typer.Exit: For ``*args`` or ``**kwargs``, which a schema can't describe.
    """
    _, described = _docs(function)
    hints = typing.get_type_hints(function)
    fields: dict[str, Any] = {}
    for name, parameter in inspect.signature(function).parameters.items():
        if name == _IDEMPOTENCY_KEY:
            continue
        if parameter.kind in (parameter.VAR_POSITIONAL, parameter.VAR_KEYWORD):
            raise fail(f"{function.__name__}: *args and **kwargs can't be described as a tool")
        default = ... if parameter.default is parameter.empty else parameter.default
        fields[name] = (hints.get(name, Any), Field(default, description=described.get(name)))
    schema = create_model(f"{function.__name__}_args", **fields).model_json_schema()
    schema.pop("title", None)
    for prop in schema.get("properties", {}).values():
        prop.pop("title", None)
    return schema


def _manifest_globs(document: CommentedMap) -> CommentedSeq:
    """The spec's ``tools.manifests`` as a list, made one if it was a single glob or missing."""
    tools = document.setdefault("tools", CommentedMap())
    globs = tools.get("manifests")
    if isinstance(globs, CommentedSeq):
        return globs
    found = CommentedSeq([globs] if isinstance(globs, str) else list(globs or []))
    tools["manifests"] = found
    return found


@add_app.command("tool")
def add_tool(
    handler: Annotated[str, typer.Argument(help="The tool's function, 'package.module:function'.")],
    path: Path_ = None,
    directory: Annotated[
        Path, typer.Option("--dir", help="Where manifests live, relative to the spec.")
    ] = Path("tools"),
    risk: Annotated[Risk, typer.Option("--risk", help="How much harm a misused call does.")] = (
        Risk.LOW
    ),
    side_effect: Annotated[
        SideEffect, typer.Option("--side-effect", help="What a call changes.")
    ] = SideEffect.NONE,
    force: Annotated[bool, typer.Option("--force", help="Overwrite an existing manifest.")] = False,
) -> None:
    """Write a tool manifest from a function's signature and docstring (S2).

    The name is the function's, the description its docstring summary, and the
    input schema comes from its parameters. Review it, then pin it with
    ``harnessweaver tools pin``.
    """
    target = spec_path(path)
    module, _, attribute = handler.partition(":")
    if not module or not attribute:
        raise fail(f"{handler!r} isn't 'package.module:function'")
    try:
        function = getattr(__import__(module, fromlist=[attribute]), attribute)
    except (ImportError, AttributeError) as exc:
        raise fail(f"can't import {handler!r} ({type(exc).__name__})") from None
    if not callable(function):
        raise fail(f"{handler!r} isn't a function")
    description, _ = _docs(function)
    if not description:
        raise fail(f"{handler} has no docstring; the model needs a description of the tool")
    name = function.__name__
    manifest = {
        "apiVersion": "harnessweaver/v1",
        "kind": "Tool",
        "metadata": {"name": name, "version": "1.0.0"},
        "spec": {
            "transport": "native",
            "handler": handler,
            "description": description,
            "input_schema": input_schema(function),
            "side_effect": side_effect.value,
            "risk": risk.value,
        },
    }
    try:
        check_schema(ToolManifest.model_validate(manifest).spec.input_schema)
    except (ValidationError, SchemaError) as exc:
        raise fail(f"{handler}: its manifest isn't valid: {exc}") from None
    base = target.resolve().parent
    file = base / directory / f"{name}.tool.yaml"
    if file.exists() and not force:
        raise fail(f"{file} already exists; use --force to overwrite")
    file.parent.mkdir(parents=True, exist_ok=True)
    header = f"# {name}: written by harnessweaver add tool. Review it, then pin it (tools pin).\n"
    file.write_text(header + _yaml.dump(manifest), encoding="utf-8")
    typer.echo(f"wrote {file.relative_to(base)}")
    # Make sure the spec reads the new manifest; add the directory's glob if it doesn't.
    document = _yaml.read(target)
    globs = _manifest_globs(document)
    relative = file.relative_to(base)
    if not any(relative.match(str(g)) for g in globs):
        globs.append(f"{directory.as_posix()}/*.tool.yaml")
        _yaml.write(target, document)
        typer.echo(f"  added {directory.as_posix()}/*.tool.yaml to tools.manifests")
    typer.echo("  next: review the description and schema, then run harnessweaver tools pin")
