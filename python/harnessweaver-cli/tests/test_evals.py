"""``harnessweaver eval run`` and ``eval report`` on a fresh extraction project."""

import json
from pathlib import Path

import anyio
from typer.testing import CliRunner

import harnessweaver as hw
from harnessweaver_cli.main import app

runner = CliRunner()


def edit(project: Path, name: str, old: str, new: str) -> None:
    path = project / name
    text = path.read_text(encoding="utf-8")
    assert old in text
    path.write_text(text.replace(old, new), encoding="utf-8")


def test_the_golden_set_passes_offline(project: Path) -> None:
    result = runner.invoke(app, ["eval", "run", "-e", "offline"])
    assert result.exit_code == 0, result.output
    assert "ok: golden (extract): 2/2 passed, pass rate 1.0 (threshold 0.9)" in result.output
    assert "no baseline yet; --update-baseline writes one" in result.output


def test_a_regression_against_the_baseline_fails(project: Path) -> None:
    written = runner.invoke(app, ["eval", "run", "-e", "offline", "--update-baseline"])
    assert written.exit_code == 0, written.output
    baseline = project / ".harness" / "baselines" / "extract.golden.json"
    assert json.loads(baseline.read_text(encoding="utf-8"))["cases"] == {
        "double-charge": True,
        "crash-on-login": True,
    }
    assert "baseline written to" in written.output
    edit(project, "harness.offline.yaml", 'contains: "crashes"', 'contains: "no such text"')
    edit(project, "evals/golden.yaml", "pass_rate: 0.9", "pass_rate: 0.5")
    result = runner.invoke(app, ["eval", "run", "-e", "offline"])
    assert result.exit_code == 1, result.output
    assert "FAIL: golden (extract): 1/2 passed" in result.output
    assert "failed crash-on-login [completed]: field_equals:category" in result.output
    assert "regressed since the baseline: crash-on-login" in result.output
    accepted = runner.invoke(app, ["eval", "run", "-e", "offline", "--update-baseline"])
    assert accepted.exit_code == 0, accepted.output  # the new results become the baseline


def test_json_output_and_shadow_guards(project: Path) -> None:
    edit(
        project,
        "harness.yaml",
        "validation:",
        "guardrails:\n  input:\n    - { id: refunds, use: topic.deny, "
        "topics: { refunds: [refund] }, mode: log_only }\n\nvalidation:",
    )
    result = runner.invoke(app, ["eval", "run", "-e", "offline", "--format", "json"])
    assert result.exit_code == 0, result.output
    (suite,) = json.loads(result.output)
    assert (suite["ok"], suite["result"]["pass_rate"], suite["baseline"]) == (True, 1.0, None)
    assert suite["shadow"] == [
        {
            "guard": "guardrails.input[refunds]",
            "runs": 2,
            "would_fire": 1,
            "rate": 0.5,
            "false_positives": ["double-charge"],
            "misses": [],
        }
    ]


def test_suites_that_cant_run_exit_2(project: Path) -> None:
    nothing = runner.invoke(app, ["eval", "run", "-e", "offline", "--suite", "nope"])
    assert nothing.exit_code == 2
    assert "no eval suites to run" in nothing.output
    edit(project, "evals/golden.yaml", "task: extract", "task: other")
    wrong = runner.invoke(app, ["eval", "run", "-e", "offline"])
    assert wrong.exit_code == 2
    assert "evals.extract lists evals/golden.yaml, whose task is other" in wrong.output
    missing = runner.invoke(app, ["eval", "run", "nowhere.yaml"])
    assert missing.exit_code == 2


def test_the_online_report(project: Path) -> None:
    empty = runner.invoke(app, ["eval", "report", "-e", "offline"])
    assert empty.exit_code == 0, empty.output
    assert "no online samples yet" in empty.output
    edit(
        project,
        "harness.yaml",
        "evals:\n",
        "state: { use: sqlite, path: .harness/state.db }\n\nevals:\n"
        "  online: { sample_rate: 1, graders: [schema_valid] }\n",
    )

    async def run_twice() -> None:
        harness = hw.load(project / "harness.yaml", env="offline")
        for text in ("I was charged twice.", "The app crashes at login."):
            await harness.run("extract", {"text": text})
        await harness.aclose()

    anyio.run(run_twice)
    result = runner.invoke(app, ["eval", "report", "-e", "offline"])
    assert result.exit_code == 0, result.output
    assert "extract: 2 samples (2 completed)" in result.output
    assert "grader schema_valid: passed 1.0" in result.output
    shown = json.loads(
        runner.invoke(app, ["eval", "report", "-e", "offline", "--format", "json"]).output
    )
    assert [(s["task"], s["samples"]) for s in shown] == [("extract", 2)]
