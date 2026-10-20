"""``harnessweaver policy test``: table-driven tests of policy rules and tool approvals.

Each row names a tool call, who makes it and what the governor must decide::

    cases:
      - id: small-refunds-pass
        tool: refund_payment
        args: { amount_usd: 20 }
        principal: { id: alice, roles: [support] }
        expect: allow
      - id: big-refunds-need-finance
        tool: refund_payment
        args: { amount_usd: 900 }
        expect: require_approval
        approver_role: finance

The governor's steps 1 to 7 decide each row as a dry run (``Harness.authorize``):
the spec's policy engine, manifests, approval rules, the trifecta and the judge,
with no rate limit used up and no tool executed. Exits 1 when a row's verdict
differs and 2 when the tests can't run.
"""

import json
from pathlib import Path
from typing import Annotated

import anyio
import typer
from pydantic import ValidationError

from harnessweaver import Harness
from harnessweaver.core.errors import HarnessError, SpecError
from harnessweaver.core.policy import PolicyCase, PolicyTests
from harnessweaver.core.tools import ToolVerdict
from harnessweaver.modules.state import MemoryStateStore
from harnessweaver.spec.yaml import load_yaml_file
from harnessweaver_cli._load import fail, load_harness
from harnessweaver_cli.spec import Env, Format, Path_, ProfileDirs

__all__ = ["policy_app"]

policy_app = typer.Typer(help="Test policy rules and tool approvals.", no_args_is_help=True)

CANT_RUN = 2
DEFAULT_CASES = Path("policy_tests.yaml")


def _read(path: Path) -> PolicyTests:
    if not path.is_file():
        raise SpecError(f"no policy tests at {path}")
    try:
        return PolicyTests.model_validate(load_yaml_file(path))
    except ValidationError as exc:
        problems = "; ".join(
            f"{'.'.join(str(p) for p in e['loc']) or '(file)'}: {e['msg']}" for e in exc.errors()
        )
        raise SpecError(f"{path}: {problems}") from None


def _mismatch(case: PolicyCase, verdict: ToolVerdict) -> str | None:
    wanted = [
        ("decision", case.expect, verdict.decision),
        ("code", case.code, verdict.code),
        ("step", case.step, verdict.step),
        ("approver_role", case.approver_role, verdict.approver_role),
    ]
    wrong = [
        f"{name} {got!r}, not {want!r}"
        for name, want, got in wanted
        if want is not None and want != got
    ]
    return "; ".join(wrong) or None


async def _check(harness: Harness, tests: PolicyTests) -> list[tuple[PolicyCase, ToolVerdict]]:
    return [
        (
            case,
            await harness.authorize(
                case.tool,
                case.args,
                principal=case.principal,
                tenant=case.tenant,
                task=case.task,
                labels=case.labels,
            ),
        )
        for case in tests.cases
    ]


@policy_app.command("test")
def run_policy_tests(
    path: Path_ = None,
    env: Env = None,
    profile_dir: ProfileDirs = None,
    cases: Annotated[
        list[Path] | None,
        typer.Option(
            "--cases", "-c", help="Test files (default: policy_tests.yaml next to the spec)."
        ),
    ] = None,
    output: Format = "text",
) -> None:
    """Check each row's tool call against the governor, without running anything.

    Exits 1 when a verdict differs from the row's expectation; 2 when the tests
    can't run.
    """
    harness = load_harness(path, env, profile_dir or [], state=MemoryStateStore(), code=CANT_RUN)
    base = harness.spec.path.parent if harness.spec.path is not None else Path.cwd()
    files = cases or [base / DEFAULT_CASES]
    results: list[tuple[Path, PolicyCase, ToolVerdict]] = []
    try:
        for file in files:
            checked = anyio.run(_check, harness, _read(file))
            results += [(file, case, verdict) for case, verdict in checked]
    except HarnessError as exc:
        raise fail(exc, CANT_RUN) from None
    failures = [(f, c, v) for f, c, v in results if _mismatch(c, v) is not None]
    if output == "json":
        body = [
            {
                "file": str(file),
                "id": case.id,
                "ok": _mismatch(case, verdict) is None,
                "expect": case.expect,
                "verdict": verdict.model_dump(mode="json"),
            }
            for file, case, verdict in results
        ]
        typer.echo(json.dumps(body, indent=2))
    else:
        for _, case, verdict in results:
            problem = _mismatch(case, verdict)
            shown = f"{verdict.decision} at step {verdict.step}"
            if problem is None:
                typer.echo(f"ok   {case.id}: {shown}")
            else:
                typer.echo(f"FAIL {case.id}: {problem} ({verdict.reason})")
        typer.echo(f"{len(results) - len(failures)} of {len(results)} policy tests passed")
    if failures:
        raise typer.Exit(code=1)
