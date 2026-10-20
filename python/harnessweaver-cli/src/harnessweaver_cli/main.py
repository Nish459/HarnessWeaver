"""Entry point for the ``harnessweaver`` command."""

from typing import Annotated

import typer

import harnessweaver
from harnessweaver_cli import __version__
from harnessweaver_cli.doctor import doctor
from harnessweaver_cli.evals import eval_app
from harnessweaver_cli.policy import policy_app
from harnessweaver_cli.replay import replay
from harnessweaver_cli.scaffold import init, run_tests
from harnessweaver_cli.spec import contracts_app, hooks, spec_app

app = typer.Typer(
    name="harnessweaver",
    help="HarnessWeaver developer tooling: weave, check and test your AI harness.",
    no_args_is_help=True,
    add_completion=False,
)
app.command()(init)
app.add_typer(spec_app, name="spec")
app.command()(doctor)
app.command()(hooks)
app.command(
    name="test", context_settings={"allow_extra_args": True, "ignore_unknown_options": True}
)(run_tests)
app.add_typer(contracts_app, name="contracts")
app.add_typer(eval_app, name="eval")
app.add_typer(policy_app, name="policy")
app.command()(replay)


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
