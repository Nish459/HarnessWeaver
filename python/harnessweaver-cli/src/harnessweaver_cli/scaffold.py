"""``harnessweaver init``: start a project from a template, and ``harnessweaver test``.

Templates are directories copied as they are; the only substitution is the
project name for the marker ``__app_name__`` in file contents (there is no
template language, R12). Built-in templates ship with the CLI; a plugin's
templates are named ``<namespace>.<template>`` (DESIGNS No. 13). Templates whose
names start with ``_`` are scaffolds for other commands (``plugin new``), not
projects.
"""

import os
import re
import subprocess
import sys
from collections.abc import Mapping
from importlib import resources
from importlib.resources.abc import Traversable
from pathlib import Path
from typing import Annotated, Final

import typer

from harnessweaver.core.errors import HarnessError
from harnessweaver.ports import TEST_MODE_ENV
from harnessweaver_cli._load import fail

__all__ = [
    "BUILTIN_TEMPLATES",
    "copy_tree",
    "init",
    "render_template",
    "run_tests",
    "template_root",
]

MARKER: Final = "__app_name__"
BUILTIN_TEMPLATES: Final = ("extraction", "rag", "agent", "workflow", "chat")
_NAME = re.compile(r"^[a-z][a-z0-9-]*$")
_SKIP = {"__pycache__", ".pytest_cache", ".DS_Store"}


def template_root(name: str) -> Traversable:
    """Where template ``name`` lives: in the CLI, or in the plugin that ships it.

    Raises:
        typer.Exit: For a template nobody ships.
    """
    if name.startswith("_"):
        raise fail(f"no template {name!r}; built-in templates: {', '.join(BUILTIN_TEMPLATES)}")
    return _root(name)


def _root(name: str) -> Traversable:
    if "." not in name:
        root = resources.files("harnessweaver_cli").joinpath("templates", name)
        if not root.is_dir():
            raise fail(f"no template {name!r}; built-in templates: {', '.join(BUILTIN_TEMPLATES)}")
        return root
    from harnessweaver.core.registry import PluginCatalog

    namespace, _, template = name.partition(".")
    try:
        loaded = PluginCatalog.default().load(namespace)
    except HarnessError as exc:
        raise fail(exc) from None
    path = loaded.plugin.templates.get(template)
    if path is None:
        raise fail(f"plugin {namespace!r} has no template {template!r}")
    return loaded.resource(path)


def _files(root: Traversable, prefix: Path = Path()) -> list[tuple[Path, Traversable]]:
    found: list[tuple[Path, Traversable]] = []
    for entry in sorted(root.iterdir(), key=lambda e: e.name):
        if entry.name in _SKIP:
            continue
        if entry.is_dir():
            found += _files(entry, prefix / entry.name)
        else:
            found.append((prefix / entry.name, entry))
    return found


def _filled(text: str, markers: Mapping[str, str]) -> str:
    for marker, value in markers.items():
        text = text.replace(marker, value)
    return text


def copy_tree(
    root: Traversable, directory: Path, markers: Mapping[str, str], *, force: bool = False
) -> list[Path]:
    """Copy the files under ``root`` into ``directory``, replacing each marker with its
    value in file contents and in paths. Returns the files written.

    Raises:
        typer.Exit: If a file would be overwritten (without ``force``).
    """
    files = [(Path(_filled(str(relative), markers)), source) for relative, source in _files(root)]
    clashes = [str(relative) for relative, _ in files if (directory / relative).exists()]
    if clashes and not force:
        raise fail(f"{', '.join(clashes)} already exist in {directory}; use --force to overwrite")
    written: list[Path] = []
    for relative, source in files:
        target = directory / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(_filled(source.read_text(encoding="utf-8"), markers), encoding="utf-8")
        written.append(target)
    return written


def render_template(
    name: str, directory: Path, app_name: str, *, force: bool = False
) -> list[Path]:
    """Copy template ``name`` into ``directory``, named ``app_name``. Returns the files written.

    Raises:
        typer.Exit: For an unknown template, or if a file would be overwritten
            (without ``force``).
    """
    return copy_tree(template_root(name), directory, {MARKER: app_name}, force=force)


def init(
    directory: Annotated[Path, typer.Argument(help="Where to create the project.")] = Path("."),
    template: Annotated[
        str, typer.Option("--template", "-t", help="A template name.")
    ] = "extraction",
    name: Annotated[
        str | None, typer.Option("--name", help="Project name (default: the directory).")
    ] = None,
    force: Annotated[bool, typer.Option("--force", help="Overwrite existing files.")] = False,
) -> None:
    """Start a project: harness.yaml, an offline overlay, code, prompts, evals and tests."""
    app_name = name or directory.resolve().name.lower().replace("_", "-")
    if not _NAME.match(app_name):
        raise fail(f"invalid project name {app_name!r}: use lowercase letters, digits and dashes")
    written = render_template(template, directory, app_name, force=force)
    typer.echo(f"created {len(written)} files in {directory} from the {template} template")
    typer.echo("next:")
    typer.echo(f"  cd {directory}")
    typer.echo("  harnessweaver spec validate --env offline")
    typer.echo("  harnessweaver test")


def run_tests(
    ctx: typer.Context,
    env: Annotated[str, typer.Option("--env", "-e", help="Overlay for the tests.")] = "offline",
) -> None:
    """Run the app's tests offline: test mode on, the offline overlay, extra args to pytest."""
    environment = {**os.environ, TEST_MODE_ENV: "1", "HARNESSWEAVER_ENV": env}
    try:
        done = subprocess.run(
            [sys.executable, "-m", "pytest", *ctx.args], env=environment, check=False
        )
    except OSError as exc:
        raise fail(f"can't run pytest ({type(exc).__name__})") from None
    raise typer.Exit(code=done.returncode)
