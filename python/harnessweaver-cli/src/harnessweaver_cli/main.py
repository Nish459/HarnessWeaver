"""Entry point for the ``harnessweaver`` command."""

from typing import Annotated

import typer

import harnessweaver
from harnessweaver_cli import __version__

app = typer.Typer(
    name="harnessweaver",
    help="HarnessWeaver developer tooling: weave, check and test your AI harness.",
    no_args_is_help=True,
    add_completion=False,
)


def _print_version(value: bool) -> None:
    if value:
        typer.echo(f"harnessweaver-cli {__version__} (harnessweaver {harnessweaver.__version__})")
        raise typer.Exit()


@app.callback()
def main(
    version: Annotated[
        bool,
        typer.Option(
            "--version", callback=_print_version, is_eager=True, help="Show versions and exit."
        ),
    ] = False,
) -> None:
    """HarnessWeaver developer tooling."""
