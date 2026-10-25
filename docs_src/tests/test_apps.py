"""Tutorial chapters 9 to 19: sessions to debugging. Each prints what its page shows."""

import os
import subprocess
import sys
from collections.abc import Callable
from typing import Any

import pytest
from typer.testing import CliRunner

import harnessweaver as hw
from harnessweaver.testing import harness_for_test, output, scripted
from harnessweaver_cli.main import app

pytestmark = pytest.mark.anyio

SetUp = Callable[[str], Any]
cli = CliRunner()

REFUND_ANSWER = "A refund takes up to five business days to reach your card [help-refunds]."

ROUTES = """\
We know about the outage and are fixing it. Updates: status.acme.example
   5 note    route.decide      harness.routing: rule 1
   8 note    route.decide      harness.decision: rule 1
Refunds go back to the card you paid with within five business days.
   5 note    route.decide      harness.routing: no rule matched
   6 note    route.decide      harness.routing: closest to billing
   9 note    route.decide      harness.decision: closest to billing
"""

TOOLS = """\
Order A-1002 has shipped; it should reach you in a day or two.
   8 hook    tool.before       harness -> continue
   9 note    tool.before       harness.governor -> continue: allowed
  10 hook    tool.after        harness -> continue
"""

APPROVAL = """\
awaiting_approval
waiting for finance: refunds over $100 need a person from finance
tool call: refund_payment {'order_id': 'A-1001', 'amount_usd': 250}
completed
Done: the refund is on its way to your card.
"""

OBSERVED = """\
completed, cost $0.000076 (known: True)
   0 hook    run.start         harness -> continue
   1 note    -                 harness.guard (guard_fired): guardrails.input[base-pii] redact
   2 outcome input.before      guardrails.input[base-pii] [baseline] -> continue: guardrails.input[base-pii]: found EMAIL
   3 outcome input.before      guardrails.input[extraction-pii] [platform] -> continue
   4 outcome input.before      guardrails.input[injection] [app] -> continue
   5 hook    input.before      harness -> continue: guardrails.input[base-pii]: found EMAIL
   6 hook    model.before      harness -> continue
   7 note    model.after       harness.budget: model usage
   8 hook    model.after       harness -> continue
   9 outcome output.before     guardrails.output[base-secrets] [baseline] -> continue
  10 outcome output.before     guardrails.output[extraction-secrets] [platform] -> continue
  11 outcome output.before     validation.rules[bugs-are-urgent] [app] -> continue
  12 outcome output.before     validation.rules[short-summary] [app] -> continue
  13 hook    output.before     harness -> continue
  14 hook    run.end           harness -> continue
"""  # noqa: E501

EVALS = """\
ok: golden (triage): 2/2 passed, pass rate 1.0 (threshold 0.9)
  shadow guardrails.input[injection]: would fire on 0/2 (0.0); false positives: none; misses: none
ok: redteam (orders): 3/3 passed, pass rate 1.0 (threshold 1.0)
  shadow guardrails.input[injection]: would fire on 1/3 (0.333333); false positives: none; misses: none
"""  # noqa: E501


async def test_sessions(chapter: SetUp, capsys: pytest.CaptureFixture[str]) -> None:
    tutorial = chapter("sessions")
    await tutorial.script("main.py").main()
    await tutorial.script("main_session.py").main()
    assert capsys.readouterr().out == (
        "completed\n"
        "Refunds go back to the card you paid with within five business days.\n"
        "How long does a refund take? I'm [EMAIL]\n"
        "Refunds go back to the card you paid with within five business days.\n"
    )
    # The rules now name the triage task, and they still apply to it.
    model = scripted(
        output({"category": "bug", "priority": 3, "summary": "Crashes."}),
        output({"category": "bug", "priority": 1, "summary": "Crashes."}),
    )
    result = await harness_for_test("harness.yaml", model=model).run(
        "triage", {"text": "It crashes."}
    )
    assert result.ok
    assert len(model.requests) == 2


async def test_routing(chapter: SetUp, capsys: pytest.CaptureFixture[str]) -> None:
    await chapter("routing").script("main.py").main()
    assert capsys.readouterr().out == ROUTES


async def test_context(chapter: SetUp, capsys: pytest.CaptureFixture[str]) -> None:
    tutorial = chapter("context")
    await tutorial.script("main.py").main()
    await tutorial.script("main_fetch.py").main()
    assert capsys.readouterr().out == (
        f"completed\n{REFUND_ANSWER}\n"
        "acme ['help-refunds', 'help-invoices']\n"
        "globex ['help-refunds', 'help-globex-sla', 'help-invoices']\n"
    )


async def test_tools(chapter: SetUp, capsys: pytest.CaptureFixture[str]) -> None:
    await chapter("tools").script("main.py").main()
    assert capsys.readouterr().out == TOOLS


async def test_policy(chapter: SetUp, capsys: pytest.CaptureFixture[str]) -> None:
    await chapter("policy").script("main.py").main()
    assert capsys.readouterr().out == (
        "completed: Done: the refund is on its way to your card.\n"
        "blocked (policy_denied): refunds over $500 go to the finance desk\n"
    )


@pytest.mark.parametrize(("name", "cases"), [("policy", 4), ("approvals", 5)])
def test_policy_tests(chapter: SetUp, name: str, cases: int) -> None:
    chapter(name)
    result = cli.invoke(app, ["policy", "test", "harness.yaml", "-e", "offline"])
    assert result.exit_code == 0, result.output
    assert result.output.endswith(f"{cases} of {cases} policy tests passed\n")


async def test_approvals(chapter: SetUp, capsys: pytest.CaptureFixture[str]) -> None:
    await chapter("approvals").script("main.py").main()
    assert capsys.readouterr().out == APPROVAL


async def test_state(chapter: SetUp, capsys: pytest.CaptureFixture[str]) -> None:
    tutorial = chapter("state")
    run_id = await tutorial.script("main.py").main()
    await tutorial.script("approve.py").main(run_id)
    assert capsys.readouterr().out == (
        f"awaiting_approval: {run_id}\ncompleted: Done: the refund is on its way to your card.\n"
    )
    async with hw.load("harness.yaml") as harness:
        report = await harness.replay(run_id)
    assert not report.differs
    assert (report.model_answers_used, report.model_answers) == (2, 2)


async def test_observability(chapter: SetUp, capsys: pytest.CaptureFixture[str]) -> None:
    await chapter("observability").script("main.py").main()
    assert capsys.readouterr().out == OBSERVED
    prod = hw.load_spec("harness.yaml", env="prod")
    assert prod.spec.observability.exporter == "otlp"


def test_testing(chapter: SetUp) -> None:
    tutorial = chapter("testing")
    env = {**os.environ, "HARNESSWEAVER_TEST_MODE": "1"}
    done = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "tests"],
        cwd=tutorial.folder,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert done.returncode == 0, done.stdout + done.stderr
    assert "5 passed" in done.stdout


def test_evals(chapter: SetUp) -> None:
    chapter("evals")
    result = cli.invoke(app, ["eval", "run", "harness.yaml", "-e", "offline"])
    assert result.exit_code == 0, result.output
    assert result.output == EVALS


def test_debugging(chapter: SetUp) -> None:
    chapter("evals")
    result = cli.invoke(app, ["spec", "validate", "harness.yaml", "-e", "offline"])
    assert result.exit_code == 0, result.output
    assert result.output.startswith("ok: support-desk is valid\n  adoption level L3 (required: L1)")
    result = cli.invoke(app, ["doctor", "harness.yaml", "-e", "offline"])
    assert result.exit_code == 0, result.output
    assert "OK    tools          2 tool manifest(s), all pinned" in result.output
