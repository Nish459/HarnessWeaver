"""The org baseline loads, and its locks, bounds and required level hold (R1, R10)."""

from pathlib import Path

import pytest

from harnessweaver.core.errors import BoundViolation, LevelTooLow, LockViolation
from harnessweaver.spec import EffectiveSpec, Level, load_spec

ORG = Path(__file__).resolve().parents[1]


def _load(tmp_path: Path, body: str) -> EffectiveSpec:
    spec = tmp_path / "harness.yaml"
    spec.write_text(
        'apiVersion: harnessweaver/v1\nkind: Harness\nextends: ["org://acme-baseline@^1"]\n' + body,
        encoding="utf-8",
    )
    return load_spec(spec, profile_dirs=[ORG])


def test_an_internal_app_at_l1_loads(tmp_path: Path) -> None:
    effective = _load(tmp_path, "metadata: { name: notes }\n")
    assert effective.spec.metadata.risk_tier == "internal"
    assert effective.level.required is Level.L1
    assert [g.id for g in effective.spec.guardrails.input] == ["base-pii"]


def test_a_customer_facing_app_needs_l2(tmp_path: Path) -> None:
    with pytest.raises(LevelTooLow):
        _load(tmp_path, "metadata: { name: notes, risk_tier: customer_facing }\n")


def test_the_pii_guard_cant_be_switched_off(tmp_path: Path) -> None:
    with pytest.raises(LockViolation):
        _load(
            tmp_path,
            "metadata: { name: notes }\n"
            "guardrails:\n  input:\n    - { id: base-pii, use: pii.regex, enabled: false }\n",
        )


def test_content_capture_stays_off(tmp_path: Path) -> None:
    with pytest.raises(LockViolation):
        _load(tmp_path, "metadata: { name: notes }\nobservability: { capture_content: true }\n")


def test_unreviewed_plugins_stay_out(tmp_path: Path) -> None:
    with pytest.raises(LockViolation):
        _load(tmp_path, "metadata: { name: notes }\nplugins: { allow: [openai, sketchy] }\n")


@pytest.mark.parametrize(
    "budget",
    [
        "budgets: { per_run: { max_usd: 9.00 } }",
        "tasks: { t: { output: str, budget: { max_usd: 3 } } }",
    ],
)
def test_budgets_are_bounded_not_clamped(tmp_path: Path, budget: str) -> None:
    with pytest.raises(BoundViolation):
        _load(tmp_path, f"metadata: {{ name: notes }}\n{budget}\n")
