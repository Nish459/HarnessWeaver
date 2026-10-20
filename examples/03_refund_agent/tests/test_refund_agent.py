"""Example 03 end to end, offline (R14, T6): the Phase 2 gate, tool governance,
policy, the lethal trifecta, approvals, Acme's own plugin, and Run and Wrap."""

import importlib.util
import json
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from types import ModuleType

import pytest
from refunds import tools
from typer.testing import CliRunner

import harnessweaver as hw
from harnessweaver.errors import LockViolation
from harnessweaver.spec import Level, load_spec
from harnessweaver.testing import harness_for_test, scripted, tool_call
from harnessweaver_cli.doctor import diagnose
from harnessweaver_cli.main import app

pytestmark = pytest.mark.anyio

HERE = Path(__file__).resolve().parents[1]
SPEC = HERE / "harness.yaml"
ORG = HERE.parent / "_org"
CASEY = hw.Principal(id="casey", roles=("customer",))
FINANCE = hw.Principal(id="fran", roles=("finance",))
SATURDAY = datetime(2026, 1, 10, 10, 0, tzinfo=UTC)


@pytest.fixture(autouse=True)
def clean_tools() -> Iterator[None]:
    tools.reset()
    yield
    tools.reset()


def offline(clock: hw.Clock | None = None) -> hw.Harness:
    """The example with its offline overlay, on a fake clock (a Monday unless given)."""
    effective = load_spec(SPEC, env="offline", profile_dirs=[ORG])
    return harness_for_test(effective, clock=clock)


def script(name: str) -> ModuleType:
    # By path, under a unique name: every example has a run.py.
    found = importlib.util.spec_from_file_location(f"example03_{name}", HERE / f"{name}.py")
    assert found is not None
    assert found.loader is not None
    module = importlib.util.module_from_spec(found)
    found.loader.exec_module(module)
    return module


async def test_the_red_team_set_passes_offline() -> None:
    """The Phase 2 gate: every injected refund attempt is blocked or waits for a person."""
    result = await offline().evaluate("evals/redteam.yaml")
    assert result.passed, [case.id for case in result.cases if not case.passed]
    assert tools.REFUNDS == []
    assert tools.EMAILS == []


async def test_the_golden_set_passes_offline() -> None:
    result = await offline().evaluate("evals/golden.yaml")
    assert result.passed, [case.id for case in result.cases if not case.passed]


async def test_run_py_waits_for_finance_then_refunds_once(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.MonkeyPatch.context() as patch:
        patch.setenv("HARNESSWEAVER_ENV", "offline")
        result = await script("run").main()
    assert result.ok, result.error
    printed = capsys.readouterr().out
    assert "waiting for finance" in printed
    assert [r["amount_usd"] for r in tools.REFUNDS] == [250]


async def test_a_small_refund_runs_on_a_weekday_but_waits_on_a_weekend() -> None:
    request = "Please refund 30 dollars for order A-1002, the box was damaged."
    weekday = await offline().run("refund", request, principal=CASEY)
    assert weekday.ok, weekday.error
    harness = offline(clock=hw.FakeClock(SATURDAY))
    weekend = await harness.run("refund", request, principal=CASEY)
    assert weekend.approval is not None
    assert weekend.approval.reason == "refunds on weekends need finance"  # acme.no_weekend_refunds
    done = await harness.approve(weekend.run_id, weekend.approval.approval_id, approver=FINANCE)
    assert done.ok, done.error
    assert [r["amount_usd"] for r in tools.REFUNDS] == [30, 30]


async def test_an_injected_order_note_cant_send_mail() -> None:
    result = await offline().run("refund", "What is the status of order A-1004?", principal=CASEY)
    assert result.status is hw.RunStatus.BLOCKED
    assert result.error is not None
    assert result.error.details["code"] == "trifecta"
    assert tools.EMAILS == []
    (verdict,) = [
        e for e in result.trace if e.source == "harness.governor" and e.code == "trifecta"
    ]
    assert verdict.details["step"] == 4


async def test_account_numbers_never_reach_the_model() -> None:
    model = scripted(tool_call("lookup_order", order_id="A-1002"), "Delivered.")
    effective = load_spec(SPEC, profile_dirs=[ORG])
    result = await harness_for_test(effective, model=model).run(
        "refund", "Where is my order A-1002?", principal=CASEY
    )
    assert result.ok, result.error
    asked = json.dumps([r.model_dump(mode="json") for r in model.requests])
    assert "ACME-10020002" not in asked
    assert "[ACCOUNT]" in asked  # acme.account_ids redacted the tool result


async def test_contractors_cant_refund() -> None:
    contractor = hw.Principal(id="carl", roles=("contractor",))
    result = await offline().run(
        "refund", "Please refund 30 dollars for order A-1002.", principal=contractor
    )
    assert result.status is hw.RunStatus.BLOCKED
    assert result.error is not None
    assert result.error.details["code"] == "policy_denied"


async def test_wrap_py_governs_the_existing_agent(capsys: pytest.CaptureFixture[str]) -> None:
    wrap = script("wrap")
    with pytest.MonkeyPatch.context() as patch:
        patch.setenv("HARNESSWEAVER_ENV", "offline")
        answer = await wrap.main()
    assert answer == "Order A-1002 was delivered."
    assert wrap.SEEN == [
        {"order_id": "A-1002", "status": "delivered", "total_usd": 80.0, "account": "[ACCOUNT]"}
    ]


def test_the_policy_tests_pass() -> None:
    result = CliRunner().invoke(
        app,
        [
            "policy",
            "test",
            str(SPEC),
            "--cases",
            str(HERE / "policy_tests.yaml"),
            "--profile-dir",
            str(ORG),
        ],
    )
    assert result.exit_code == 0, result.output
    assert "6 of 6 policy tests passed" in result.output


@pytest.mark.parametrize(
    "overlay",
    [
        "tools: { require_manifest: false }\n",
        "tools: { approval_by_risk: { high: none } }\n",
        "guardrails:\n  output:\n    - { id: base-secrets, use: secrets.scan, mode: log_only }\n",
    ],
)
def test_the_baseline_cant_be_loosened(tmp_path: Path, overlay: str) -> None:
    (tmp_path / "harness.yaml").write_text(SPEC.read_text(encoding="utf-8"), encoding="utf-8")
    (tmp_path / "harness.loose.yaml").write_text(overlay, encoding="utf-8")
    with pytest.raises(LockViolation):
        load_spec(tmp_path / "harness.yaml", env="loose", profile_dirs=[ORG])


def test_doctor_reports_l4_for_an_app_that_takes_actions() -> None:
    effective = load_spec(SPEC, profile_dirs=[ORG])
    assert (effective.level.level, effective.level.required) == (Level.L4, Level.L3)
    findings = diagnose(SPEC, "offline", [ORG])
    assert findings[0].message.startswith("adoption level L4")
    assert not [f for f in findings if f.severity == "fail"]
