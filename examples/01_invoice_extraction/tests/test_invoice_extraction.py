"""Example 01 end to end, offline (R14, T6): the Phase 1 gate in tests."""

import ast
import importlib.util
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
from invoices.models import Invoice, InvoiceDoc
from invoices.samples import EXPECTED, INVOICE_TEXT

import harnessweaver as hw
from harnessweaver.spec import Level
from harnessweaver.testing import (
    assert_no_content,
    assert_trace,
    harness_for_test,
    output,
    scripted,
    step,
)
from harnessweaver_cli.doctor import diagnose

pytestmark = pytest.mark.anyio

HERE = Path(__file__).resolve().parents[1]
SPEC = HERE / "harness.yaml"
DOC = InvoiceDoc(text=INVOICE_TEXT)


def answer(**changes: Any) -> dict[str, Any]:
    return {**EXPECTED, **changes}


def script(name: str) -> ModuleType:
    # By path, under a unique name: every example has a run.py.
    found = importlib.util.spec_from_file_location(f"example01_{name}", HERE / f"{name}.py")
    assert found is not None
    assert found.loader is not None
    module = importlib.util.module_from_spec(found)
    found.loader.exec_module(module)
    return module


async def test_the_golden_set_passes_offline() -> None:
    result = await hw.load(SPEC, env="offline").evaluate("evals/golden.yaml")
    assert result.passed, [case.id for case in result.cases if not case.passed]
    assert result.grader_rates == {
        "schema_valid": 1.0,
        "field_equals:invoice_number": 1.0,
        "field_equals:total": 1.0,
    }


async def test_the_offline_run_repairs_the_first_answer() -> None:
    harness = hw.load(SPEC, env="offline")
    result = await harness.run("extract_invoice", DOC, principal="ap-clerk", tenant="acme")
    assert result.ok
    assert Invoice.model_validate(result.output) == Invoice.model_validate(EXPECTED)
    assert_trace(
        result,
        "input.before",
        "model.after",
        step(code="repair"),
        "model.after",
        "output.before",
        "run.end",
    )
    assert result.cost_usd is not None
    assert 0 < result.cost_usd <= 0.02


async def test_the_spec_is_at_l1() -> None:
    assert hw.load(SPEC, env="offline").spec.level.level is Level.L1


async def test_a_total_that_doesnt_add_up_is_repaired() -> None:
    model = scripted(output(answer(total=2170.0)), output(EXPECTED))
    result = await harness_for_test(SPEC, model=model).run("extract_invoice", DOC)
    assert result.ok
    assert "subtotal plus the tax must equal the total" in model.requests[1].messages[-1].content


async def test_a_second_bad_answer_goes_to_a_person() -> None:
    model = scripted(output(answer(line_items=[])))
    result = await harness_for_test(SPEC, model=model).run("extract_invoice", DOC)
    assert result.status is hw.RunStatus.ESCALATED
    assert len(model.requests) == 2


async def test_emails_and_phone_numbers_never_reach_the_model() -> None:
    model = scripted(output(EXPECTED))
    result = await harness_for_test(SPEC, model=model).run("extract_invoice", DOC)
    sent = model.requests[0].messages[-1].content
    assert "accounts@example.com" not in sent
    assert "555-123-4567" not in sent
    assert "[EMAIL]" in sent
    assert_no_content(result, "accounts@example.com", "555-123-4567")


async def test_a_secret_in_the_answer_blocks_the_run() -> None:
    model = scripted(output(answer(vendor="Northwind AKIAIOSFODNN7EXAMPLE")))
    result = await harness_for_test(SPEC, model=model).run("extract_invoice", DOC)
    assert result.status is hw.RunStatus.BLOCKED
    assert_no_content(result, "AKIAIOSFODNN7EXAMPLE")  # R9: findings, never the secret


async def test_a_caller_can_lower_the_budget_but_not_raise_it() -> None:
    harness = harness_for_test(SPEC, model=scripted(output(EXPECTED)))
    lowered = await harness.run("extract_invoice", DOC, budget={"max_usd": 0.0000001})
    assert lowered.status is hw.RunStatus.BLOCKED
    with pytest.raises(hw.errors.BoundViolation):
        await harness.run("extract_invoice", DOC, budget={"max_usd": 1.0})


async def test_run_py_prints_the_invoice(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.MonkeyPatch.context() as patch:
        patch.setenv("HARNESSWEAVER_ENV", "offline")
        result = await script("run").main()
    assert result.ok
    assert "total: 1860.00 EUR over 2 lines" in capsys.readouterr().out


async def test_l0_instrument_redacts_before_the_gateway(capsys: pytest.CaptureFixture[str]) -> None:
    l0_instrument = script("l0_instrument")
    with pytest.MonkeyPatch.context() as patch:
        patch.setenv("HARNESSWEAVER_ENV", "offline")
        invoice = await l0_instrument.main()
    assert invoice.total == 1860.0
    printed = capsys.readouterr().out
    assert "Billed to: Acme Corp, [EMAIL]" in printed
    assert "accounts@example.com" not in "".join(l0_instrument.RECEIVED)


def test_l0_is_three_lines() -> None:
    marked = [
        line
        for line in (HERE / "l0_instrument.py").read_text(encoding="utf-8").splitlines()
        if line.rstrip().endswith(("# 1", "# 2", "# 3"))
    ]
    assert len(marked) == 3


def test_doctor_reports_l1() -> None:
    findings = diagnose(SPEC, "offline", [])
    assert not [f for f in findings if f.severity != "ok"]
    assert findings[0].message.startswith("adoption level L1")


@pytest.mark.parametrize("path", ["run.py", "l0_instrument.py", "invoices/models.py"])
def test_the_app_has_no_retry_or_tracing_code(path: str) -> None:
    tree = ast.parse((HERE / path).read_text(encoding="utf-8"))
    imported = {
        name.split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.Import | ast.ImportFrom)
        for name in (
            [a.name for a in node.names] if isinstance(node, ast.Import) else [node.module or ""]
        )
    }
    assert not imported & {"opentelemetry", "tenacity", "backoff", "logging"}
    assert not [n for n in ast.walk(tree) if isinstance(n, ast.Try | ast.While)]
