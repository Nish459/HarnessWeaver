"""``harnessweaver eval run`` and ``eval report`` (DESIGNS No. 23).

``eval run`` runs the spec's eval suites (``evals: {task: [files]}``) with the
runs kept in memory, compares each with its baseline in
``.harness/baselines/<task>.<suite>.json`` and reports the guards in shadow mode.
It exits 1 when a suite misses its threshold or a case that passed in the
baseline fails, and 2 when the suites can't run. ``eval report`` summarizes the
production runs ``evals.online`` sampled.
"""

import json
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Any

import anyio
import typer
from pydantic import ValidationError

from harnessweaver import Harness
from harnessweaver.core.errors import HarnessError, SpecError
from harnessweaver.core.evals import (
    Baseline,
    Comparison,
    EvalDataset,
    OnlineSample,
    ShadowGuardReport,
    SuiteResult,
)
from harnessweaver.modules.evals import (
    compare,
    load_dataset,
    online_shadow_report,
    shadow_guards,
    suite_shadow_report,
)
from harnessweaver.modules.state import MemoryStateStore
from harnessweaver_cli._load import fail, load_harness
from harnessweaver_cli.spec_commands import Env, Format, Path_, ProfileDirs

__all__ = ["eval_app"]

eval_app = typer.Typer(help="Run eval suites and read online samples.", no_args_is_help=True)

CANT_RUN = 2
BASELINES = Path(".harness") / "baselines"

Names = Annotated[list[str] | None, typer.Option(help="Only these (repeatable).")]


@dataclass
class _Suite:
    dataset: EvalDataset
    result: SuiteResult
    baseline: Path
    comparison: Comparison
    had_baseline: bool
    shadow: list[ShadowGuardReport]
    updated: bool = False

    def ok(self, updating: bool) -> bool:
        return self.result.passed and (updating or not self.comparison.regression)


def _base(harness: Harness) -> Path:
    path = harness.spec.path
    return path.parent if path is not None else Path.cwd()


def _datasets(harness: Harness, tasks: list[str], suites: list[str]) -> list[EvalDataset]:
    found: list[EvalDataset] = []
    for task, files in harness.spec.spec.evals.suites().items():
        if tasks and task not in tasks:
            continue
        for file in files:
            path = Path(file) if Path(file).is_absolute() else _base(harness) / file
            dataset = load_dataset(path)
            if dataset.task != task:
                raise SpecError(f"evals.{task} lists {file}, whose task is {dataset.task}")
            if not suites or dataset.suite in suites:
                found.append(dataset)
    if not found:
        raise SpecError("no eval suites to run; list datasets under evals: {task: [files]}")
    return found


def _read_baseline(path: Path) -> Baseline | None:
    if not path.is_file():
        return None
    try:
        return Baseline.model_validate_json(path.read_text(encoding="utf-8"))
    except ValidationError:
        raise SpecError(
            f"{path} isn't a baseline; delete it or run with --update-baseline"
        ) from None


async def _run_suites(
    harness: Harness, datasets: list[EvalDataset], baselines: Path, update: bool
) -> list[_Suite]:
    done: list[_Suite] = []
    for dataset in datasets:
        result = await harness.evaluate(dataset)
        path = baselines / f"{dataset.task}.{dataset.suite}.json"
        baseline = _read_baseline(path)
        suite = _Suite(
            dataset=dataset,
            result=result,
            baseline=path,
            comparison=compare(baseline, {c.id: c.passed for c in result.cases}),
            had_baseline=baseline is not None,
            shadow=suite_shadow_report(harness.spec.spec, dataset, result),
        )
        if update and result.passed:
            written = Baseline(
                suite=dataset.suite,
                task=dataset.task,
                pass_rate=result.pass_rate,
                cases={c.id: c.passed for c in result.cases},
            )
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(written.model_dump_json(indent=2) + "\n", encoding="utf-8")
            suite.updated = True
        done.append(suite)
    return done


def _listed(ids: tuple[str, ...] | None) -> str:
    return ", ".join(ids) if ids else "none"


def _print(suite: _Suite, updating: bool) -> None:
    result = suite.result
    passed = sum(1 for c in result.cases if c.passed)
    typer.echo(
        f"{'ok' if suite.ok(updating) else 'FAIL'}: {result.suite} ({result.task}): "
        f"{passed}/{len(result.cases)} passed, pass rate {result.pass_rate} "
        f"(threshold {result.threshold})"
    )
    for case in result.cases:
        if not case.passed:
            failed = "; ".join(
                g.grader + (f" ({g.reason})" if g.reason else "")
                for g in case.grades
                if not g.passed
            )
            typer.echo(f"  failed {case.id} [{case.status.value}]: {failed}")
    found = suite.comparison
    if found.regressed:
        typer.echo(f"  regressed since the baseline: {', '.join(found.regressed)}")
    if found.fixed:
        typer.echo(f"  fixed since the baseline: {', '.join(found.fixed)}")
    if not suite.had_baseline and not suite.updated:
        typer.echo("  no baseline yet; --update-baseline writes one")
    for guard in suite.shadow:
        typer.echo(
            f"  shadow {guard.guard}: would fire on {guard.would_fire}/{guard.runs} "
            f"({guard.rate}); false positives: {_listed(guard.false_positives)}; "
            f"misses: {_listed(guard.misses)}"
        )
    if suite.updated:
        typer.echo(f"  baseline written to {suite.baseline}")


@eval_app.command("run")
def run(
    path: Path_ = None,
    env: Env = None,
    profile_dir: ProfileDirs = None,
    suite: Names = None,
    task: Names = None,
    baselines: Annotated[
        Path | None,
        typer.Option(help="Where baselines live (default: .harness/baselines next to the spec)."),
    ] = None,
    update_baseline: Annotated[
        bool, typer.Option("--update-baseline", help="Accept these results as the baselines.")
    ] = False,
    output: Format = "text",
) -> None:
    """Run the eval suites, compare them with their baselines and report shadow guards.

    Exits 1 when a suite misses its pass-rate threshold or a case that passed in
    the baseline fails; 2 when the suites can't run.
    """
    harness = load_harness(path, env, profile_dir or [], state=MemoryStateStore(), code=CANT_RUN)
    try:
        datasets = _datasets(harness, task or [], suite or [])
        where = baselines or _base(harness) / BASELINES
        suites = anyio.run(_run_suites, harness, datasets, where, update_baseline)
    except HarnessError as exc:
        raise fail(exc, CANT_RUN) from None
    if output == "json":
        body = [
            {
                "suite": s.dataset.suite,
                "task": s.dataset.task,
                "ok": s.ok(update_baseline),
                "result": s.result.model_dump(mode="json"),
                "comparison": {**s.comparison.model_dump(), "regression": s.comparison.regression},
                "baseline": str(s.baseline) if s.had_baseline or s.updated else None,
                "baseline_updated": s.updated,
                "shadow": [g.model_dump(mode="json") for g in s.shadow],
            }
            for s in suites
        ]
        typer.echo(json.dumps(body, indent=2))
    else:
        for s in suites:
            _print(s, update_baseline)
    if not all(s.ok(update_baseline) for s in suites):
        raise typer.Exit(code=1)


def _summary(task: str | None, samples: list[OnlineSample], guards: list[str]) -> dict[str, Any]:
    rates: dict[str, list[int]] = {}
    for sample in samples:
        for grade in sample.grades:
            counts = rates.setdefault(grade.grader, [0, 0])
            counts[0] += grade.passed
            counts[1] += 1
    return {
        "task": task,
        "samples": len(samples),
        "statuses": dict(Counter(s.status.value for s in samples)),
        "graders": {label: round(ok / of, 6) for label, (ok, of) in rates.items()},
        "shadow": [g.model_dump(mode="json") for g in online_shadow_report(guards, samples)],
    }


@eval_app.command("report")
def report(
    path: Path_ = None,
    env: Env = None,
    profile_dir: ProfileDirs = None,
    task: Annotated[str | None, typer.Option(help="Only this task.")] = None,
    output: Format = "text",
) -> None:
    """Summarize the production runs evals.online sampled: statuses, grader pass rates and
    how often each guard in shadow mode would have fired (R8)."""
    harness = load_harness(path, env, profile_dir or [], code=CANT_RUN)

    async def read() -> list[OnlineSample]:
        try:
            return await harness.samples(task)
        finally:
            await harness.aclose()

    samples = anyio.run(read)
    tasks = sorted({s.task or "" for s in samples})
    spec = harness.spec.spec
    body = [
        _summary(
            name or None,
            [s for s in samples if (s.task or "") == name],
            shadow_guards(spec, name or None),
        )
        for name in tasks
    ]
    if output == "json":
        typer.echo(json.dumps(body, indent=2))
        return
    if not body:
        typer.echo("no online samples yet; set evals.online.sample_rate to sample runs")
        return
    for summary in body:
        statuses = ", ".join(f"{n} {status}" for status, n in summary["statuses"].items())
        typer.echo(f"{summary['task'] or '(no task)'}: {summary['samples']} samples ({statuses})")
        for label, rate in summary["graders"].items():
            typer.echo(f"  grader {label}: passed {rate}")
        for guard in summary["shadow"]:
            typer.echo(
                f"  shadow {guard['guard']}: would fire on {guard['would_fire']}/{guard['runs']} "
                f"({guard['rate']})"
            )
