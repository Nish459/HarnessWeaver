"""Tutorial chapters 1 to 8: first steps to profiles. Each prints what its page shows."""

from collections.abc import Callable
from typing import Any

import pytest

import harnessweaver as hw
from harnessweaver.errors import BoundViolation, LockViolation
from harnessweaver.testing import harness_for_test, scripted

pytestmark = pytest.mark.anyio

SetUp = Callable[[str], Any]

FIRST_TRACE = """\
completed
billing, priority 2: charged twice for the Pro plan, wants one refund.
   0 hook    run.start         harness -> continue
   1 hook    input.before      harness -> continue
   2 hook    model.before      harness -> continue
   3 note    model.after       harness.budget: model usage
   4 hook    model.after       harness -> continue
   5 hook    output.before     harness -> continue
   6 hook    run.end           harness -> continue
"""

REPAIR_TRACE = """\
completed
bug, priority 1: The app crashes at login since this morning's update.
   0 hook    run.start         harness -> continue
   1 hook    input.before      harness -> continue
   2 hook    model.before      harness -> continue
   3 note    model.after       harness.budget: model usage
   4 hook    model.after       harness -> continue
   5 outcome output.before     validation.rules[bugs-are-urgent] [app] -> retry: a bug is priority 1 or 2
   6 outcome output.before     validation.rules[short-summary] [app] -> continue
   7 hook    output.before     harness -> retry: a bug is priority 1 or 2
   8 note    output.before     harness.validation (repair): repair 1: a bug is priority 1 or 2
   9 hook    model.before      harness -> continue
  10 note    model.after       harness.budget: model usage
  11 hook    model.after       harness -> continue
  12 outcome output.before     validation.rules[bugs-are-urgent] [app] -> continue
  13 outcome output.before     validation.rules[short-summary] [app] -> continue
  14 hook    output.before     harness -> continue
  15 hook    run.end           harness -> continue
"""  # noqa: E501

GUARDS = """\
completed
   1 note    -                 harness.guard (guard_fired): guardrails.input[pii] redact
completed
   2 note    -                 harness.guard (guard_shadow): guardrails.input[injection] would block
"""


async def test_first_steps(chapter: SetUp, capsys: pytest.CaptureFixture[str]) -> None:
    tutorial = chapter("first_steps")
    await tutorial.script("main.py").main()
    assert capsys.readouterr().out == (
        "completed\nbilling, priority 2: charged twice for the Pro plan, wants one refund.\n"
    )
    await tutorial.script("main_trace.py").main()
    assert capsys.readouterr().out == FIRST_TRACE


async def test_models(chapter: SetUp, capsys: pytest.CaptureFixture[str]) -> None:
    tutorial = chapter("models")
    await tutorial.script("main.py").main()
    assert capsys.readouterr().out.splitlines()[2:] == ["tokens: 12 in, 18 out", "cost: $0.000039"]
    prod = hw.load_spec("harness.yaml", env="prod")
    assert prod.spec.models.aliases["fast"] == "fast-chat-prod"


async def test_prompts(chapter: SetUp, capsys: pytest.CaptureFixture[str]) -> None:
    tutorial = chapter("prompts")
    await tutorial.script("main.py").main()
    assert capsys.readouterr().out.startswith("completed\n")
    # The page says the prompt is the system message and the input the user message.
    model = scripted("ok")
    await harness_for_test("harness.yaml", model=model).run("triage", "Help!")
    system, user = model.requests[0].messages
    assert system.role == "system"
    assert system.content.startswith("You triage messages")
    assert (user.role, user.content) == ("user", "Help!")


async def test_typed_output(chapter: SetUp, capsys: pytest.CaptureFixture[str]) -> None:
    await chapter("typed_output").script("main.py").main()
    assert capsys.readouterr().out == (
        "completed\n"
        "billing, priority 2: Charged twice for the Pro plan and wants one payment refunded.\n"
    )


async def test_validation(chapter: SetUp, capsys: pytest.CaptureFixture[str]) -> None:
    await chapter("validation").script("main.py").main()
    assert capsys.readouterr().out == REPAIR_TRACE


async def test_budgets(chapter: SetUp, capsys: pytest.CaptureFixture[str]) -> None:
    tutorial = chapter("budgets")
    await tutorial.script("main.py").main()
    assert capsys.readouterr().out == (
        "completed, cost $0.000155\nblocked (budget_exceeded): budget max_model_calls (1) reached\n"
    )
    harness = hw.load("harness.yaml")
    ticket = tutorial.script("main.py").TICKET
    with pytest.raises(BoundViolation, match="may only lower"):
        await harness.run("triage", ticket, budget={"max_model_calls": 5})
    with pytest.raises(BoundViolation, match="can't be overridden"):
        await harness.run("triage", ticket, budget={"deadline": "10s"})


async def test_guardrails(chapter: SetUp, capsys: pytest.CaptureFixture[str]) -> None:
    await chapter("guardrails").script("main.py").main()
    assert capsys.readouterr().out == GUARDS


async def test_profiles(chapter: SetUp, capsys: pytest.CaptureFixture[str]) -> None:
    await chapter("profiles").script("main.py").main()
    assert capsys.readouterr().out.startswith("completed\nbilling, priority 2:")
    with pytest.raises(LockViolation, match=r"guardrails.input\[base-pii\].enabled is locked"):
        hw.load_spec("harness.yaml", env="loose")


async def test_home_page_example(chapter: SetUp, capsys: pytest.CaptureFixture[str]) -> None:
    await chapter("home").script("main.py").main()
    assert capsys.readouterr().out == (
        "billing, priority 2: Charged twice for the Pro plan and wants one payment refunded.\n"
        "completed\n"
        "harness.guard (guard_fired): guardrails.input[extraction-pii] redact\n"
    )
