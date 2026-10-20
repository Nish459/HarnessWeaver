"""``harnessweaver spec validate|explain|diff``, ``hooks`` and ``contracts export``."""

import json
from pathlib import Path
from typing import Annotated, Literal

import typer
from rich import box
from rich.console import Console
from rich.markup import escape
from rich.table import Table

from harnessweaver import HookPoint
from harnessweaver.contracts import stale_schemas, write_schemas
from harnessweaver.spec import diff_specs, render_diff, render_explain
from harnessweaver_cli._load import load_effective, load_harness, spec_path

__all__ = ["contracts_app", "hooks", "spec_app"]

spec_app = typer.Typer(help="Validate, explain and diff harness.yaml.", no_args_is_help=True)
contracts_app = typer.Typer(help="Work with the language-neutral contracts.", no_args_is_help=True)

Path_ = Annotated[Path | None, typer.Argument(help="The app spec (default: harness.yaml).")]
Env = Annotated[str | None, typer.Option("--env", "-e", help="Overlay: harness.<env>.yaml.")]
ProfileDirs = Annotated[
    list[Path] | None, typer.Option("--profile-dir", help="Also search here for org:// profiles.")
]
Format = Annotated[Literal["text", "json"], typer.Option("--format", help="Output format.")]


def _console() -> Console:
    return Console(width=120, highlight=False, soft_wrap=True)


@spec_app.command("validate")
def validate(
    path: Path_ = None, env: Env = None, profile_dir: ProfileDirs = None, output: Format = "text"
) -> None:
    """Load the spec as the app would: layers, locks, bounds, plugins, tasks, hooks (R4)."""
    harness = load_harness(path, env, profile_dir or [])
    level = harness.spec.level
    if output == "json":
        body = {
            "ok": True,
            "name": harness.name,
            "level": level.level.value,
            "required": level.required.value,
            "tasks": harness.tasks,
            "layers": [p.describe() for p in harness.spec.layers],
        }
        typer.echo(json.dumps(body, indent=2))
        return
    typer.echo(f"ok: {harness.name} is valid")
    typer.echo(f"  adoption level {level.level.value} (required: {level.required.value})")
    typer.echo(f"  layers: {', '.join(p.describe() for p in harness.spec.layers)}")
    typer.echo(f"  tasks: {', '.join(harness.tasks) or '(none)'}")


@spec_app.command("explain")
def explain(
    path: Path_ = None,
    env: Env = None,
    profile_dir: ProfileDirs = None,
    prefix: Annotated[
        str | None, typer.Option("--path", help="Only paths starting with this.")
    ] = None,
    output: Format = "text",
) -> None:
    """Show every effective value, the layer it came from, and its locks and bounds."""
    effective = load_effective(str(spec_path(path)), env, profile_dir or [])
    rows = [r for r in effective.explain() if prefix is None or r.path.startswith(prefix)]
    if output == "json":
        body = [
            {
                "path": r.path,
                "value": r.value,
                "layer": r.origin.layer if r.origin else None,
                "locked_by": r.locked_by.declared_by.layer if r.locked_by else None,
            }
            for r in rows
        ]
        typer.echo(json.dumps(body, indent=2))
        return
    typer.echo(render_explain(rows))


@spec_app.command("diff")
def diff(
    before: Annotated[str, typer.Argument(help="Old spec: a path, or git:<ref>:<path>.")],
    after: Annotated[str, typer.Argument(help="New spec: a path, or git:<ref>:<path>.")],
    env: Env = None,
    profile_dir: ProfileDirs = None,
    exit_code: Annotated[
        bool, typer.Option("--exit-code", help="Exit 1 when the effective specs differ.")
    ] = False,
) -> None:
    """Compare two effective specs as Markdown: values, locks and adoption level."""
    dirs = profile_dir or []
    result = diff_specs(load_effective(before, env, dirs), load_effective(after, env, dirs))
    typer.echo(render_diff(result))
    if exit_code and not result.empty:
        raise typer.Exit(code=1)


def hooks(
    path: Path_ = None,
    env: Env = None,
    profile_dir: ProfileDirs = None,
    task: Annotated[str | None, typer.Option("--task", help="Show a task's chains.")] = None,
) -> None:
    """Show the middleware on every hook point, in the order it runs (DESIGNS No. 8)."""
    harness = load_harness(path, env, profile_dir or [])
    reaches = harness.runner_of(task).reaches if task is not None else None
    title = f"{harness.name} hooks" + (f" for task {task}" if task else "")
    table = Table(title=escape(title), box=box.ASCII)
    for column in ("hook", "order", "middleware", "band", "fail mode", "timeout"):
        table.add_column(column)
    for hook, chain in harness.hooks(task).items():
        label = hook.value
        if reaches is not None and hook not in reaches:
            label += " (not reached)"
        if not chain:
            table.add_row(label, "-", "-", "", "", "")
        for position, registration in enumerate(chain, start=1):
            timeout = f"{registration.timeout.total_seconds():g}s" if registration.timeout else ""
            table.add_row(
                label if position == 1 else "",
                str(position),
                escape(registration.name),
                registration.band.value,
                registration.fail_mode,
                timeout,
            )
    console = _console()
    console.print(table)
    direction = {h.value: h.direction.value for h in HookPoint}
    console.print(
        "inbound hooks run baseline -> task; outbound hooks run task -> baseline: "
        + ", ".join(sorted(k for k, v in direction.items() if v == "outbound"))
    )


@contracts_app.command("export")
def export(
    out: Annotated[Path, typer.Argument(help="Directory for the JSON Schemas.")] = Path(
        "contracts/schemas"
    ),
    check: Annotated[bool, typer.Option("--check", help="Report drift; write nothing.")] = False,
) -> None:
    """Write the JSON Schema of every contract (harness.yaml, events, outcomes, ...)."""
    if check:
        problems = stale_schemas(out)
        for problem in problems:
            typer.echo(problem)
        if problems:
            raise typer.Exit(code=1)
        typer.echo(f"ok: the schemas in {out} are up to date")
        return
    written = write_schemas(out)
    typer.echo(f"wrote {len(written)} schemas to {out}")
