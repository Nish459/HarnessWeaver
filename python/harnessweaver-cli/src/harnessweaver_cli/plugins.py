"""``harnessweaver plugin new`` and ``harnessweaver plugin list`` (DESIGNS No. 13).

``plugin new`` scaffolds a standalone plugin package, meant to live in its own
repository: it builds on the public extension surface only and passes the
conformance suite as written. ``plugin list`` shows what is installed.
"""

import json
from importlib import resources
from pathlib import Path
from typing import Annotated, Any

import typer
from rich import box
from rich.console import Console
from rich.table import Table

from harnessweaver import CONTRACT_VERSION, RESERVED_NAMESPACES
from harnessweaver.core.errors import HarnessError
from harnessweaver.core.plugins.names import NAMESPACE_PATTERN
from harnessweaver.core.registry import PluginCatalog
from harnessweaver_cli._load import fail
from harnessweaver_cli.scaffold import copy_tree
from harnessweaver_cli.spec import Format

__all__ = ["plugin_app"]

plugin_app = typer.Typer(help="Create and inspect plugins.", no_args_is_help=True)


@plugin_app.command("new")
def new(
    namespace: Annotated[str, typer.Argument(help="The plugin's namespace, such as acme.")],
    directory: Annotated[
        Path | None, typer.Argument(help="Where to create it (default: ./<namespace>-harness).")
    ] = None,
    force: Annotated[bool, typer.Option("--force", help="Overwrite existing files.")] = False,
) -> None:
    """Scaffold a standalone plugin package: entry point, ``hw.Plugin``, a sample guard
    and tests that also run the conformance suite (T5)."""
    if not NAMESPACE_PATTERN.match(namespace):
        raise fail(
            f"invalid namespace {namespace!r}: use lowercase letters, digits and underscores, "
            "starting with a letter"
        )
    if namespace in RESERVED_NAMESPACES:
        raise fail(f"namespace {namespace!r} is reserved for the built-in plugin")
    dist = f"{namespace.replace('_', '-')}-harness"
    target = directory or Path(dist)
    root = resources.files("harnessweaver_cli").joinpath("templates", "_plugin")
    written = copy_tree(root, target, {"__dist__": dist, "__ns__": namespace}, force=force)
    typer.echo(f"created {len(written)} files in {target} for the plugin {namespace!r} ({dist})")
    typer.echo("next:")
    typer.echo(f"  cd {target}")
    typer.echo("  uv sync && uv run pytest     # its tests and the conformance suite")


def _row(catalog: PluginCatalog, namespace: str, sources: tuple[Any, ...]) -> dict[str, Any]:
    """What ``plugin list`` shows for one namespace. Importing a plugin does no I/O (S8)."""
    source = sources[0]
    row: dict[str, Any] = {
        "namespace": namespace,
        "distribution": source.distribution,
        "target": source.target,
    }
    try:
        plugin = catalog.load(namespace).plugin
    except HarnessError as exc:  # several claim it, or it doesn't import
        row.update(version=None, contract=None, compatible=False, problem=exc.message)
        return row
    row.update(
        version=plugin.version,
        contract=plugin.contract,
        compatible=plugin.contract_range.contains(CONTRACT_VERSION),
        contributions=len(plugin.contributions()),
        problem=None,
    )
    return row


@plugin_app.command("list")
def list_plugins(output: Format = "text") -> None:
    """Installed plugins: namespace, distribution, version, contract range and whether it
    is compatible with this harnessweaver (V5)."""
    catalog = PluginCatalog.default()
    rows = [_row(catalog, ns, sources) for ns, sources in catalog.sources().items()]
    if output == "json":
        typer.echo(json.dumps({"plugins": rows, "problems": catalog.problems()}, indent=2))
        return
    table = Table(box=box.SIMPLE, show_header=True)
    for column in ("namespace", "distribution", "version", "contract", "compatible"):
        table.add_column(column)
    for row in rows:
        compatible = "yes" if row["compatible"] else f"no: {row['problem'] or 'contract range'}"
        table.add_row(
            row["namespace"],
            row["distribution"] or "-",
            row["version"] or "-",
            row["contract"] or "-",
            compatible,
        )
    Console(width=120, highlight=False).print(table)
    for problem in catalog.problems():
        typer.echo(f"warning: {problem}")
    typer.echo(f"harnessweaver contract {CONTRACT_VERSION}")
