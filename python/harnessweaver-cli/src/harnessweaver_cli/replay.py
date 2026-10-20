"""``harnessweaver replay <run_id>``: run a recorded run again against the current code
and spec (ADR-0035).

The run must have been recorded (``state.record: true``). Its model answers and
tool results come from the recording, so nothing calls out and no tool runs;
the replay's own runs stay in memory. Exits 1 when the status or the output
changed, and 2 when the run can't be replayed.
"""

import json

import anyio
import typer

from harnessweaver import Harness
from harnessweaver.core.errors import HarnessError
from harnessweaver.core.replay import ReplayReport
from harnessweaver_cli._load import fail, load_harness
from harnessweaver_cli.spec import Env, Format, Path_, ProfileDirs

__all__ = ["replay"]

CANT_RUN = 2


async def _replay(harness: Harness, run_id: str) -> ReplayReport:
    try:
        return await harness.replay(run_id)
    finally:
        await harness.aclose()


def _print(report: ReplayReport) -> None:
    before, after = report.original, report.replayed
    typer.echo(
        f"{'changed' if report.differs else 'same'}: run {report.run_id} ({report.task}) "
        f"ended {before.status.value}; the replay ended {after.status.value}"
    )
    typer.echo(f"  output: {'same' if report.same_output else 'different'}")
    typer.echo(
        f"  model answers used: {report.model_answers_used} of {report.model_answers}"
        + (f"; {report.changed_requests} request(s) changed" if report.changed_requests else "")
    )
    if report.missing_tool_results:
        typer.echo(f"  tool calls not in the recording: {report.missing_tool_results}")
    for change in report.changes:
        sign = "+" if change.change == "added" else "-"
        where = change.hook.value if change.hook is not None else "-"
        what = change.code or (change.outcome.value if change.outcome else "")
        typer.echo(f"  {sign} {where} {change.source} {what}: {change.reason or ''}".rstrip(": "))


def replay(
    run_id: str = typer.Argument(help="The recorded run."),
    path: Path_ = None,
    env: Env = None,
    profile_dir: ProfileDirs = None,
    output: Format = "text",
) -> None:
    """Replay a recorded run against the current code and spec, and show what changed.

    Exits 1 when the status or output changed; 2 when the run can't be replayed.
    """
    harness = load_harness(path, env, profile_dir or [], code=CANT_RUN)
    try:
        report = anyio.run(_replay, harness, run_id)
    except HarnessError as exc:
        raise fail(exc, CANT_RUN) from None
    if output == "json":
        body = {**report.model_dump(mode="json"), "differs": report.differs}
        typer.echo(json.dumps(body, indent=2))
    else:
        _print(report)
    if report.differs:
        raise typer.Exit(code=1)
