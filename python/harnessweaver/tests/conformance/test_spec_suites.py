"""Python runners for the spec suites: merge (layers, locks, bounds, run budgets) and levels."""

from pathlib import Path
from typing import Any

import pytest

from harnessweaver.core.errors import BoundViolation, LockViolation, SpecError
from harnessweaver.spec.levels import assess
from harnessweaver.spec.loader import spec_from_documents
from harnessweaver.spec.merge import Layer, LayerKind, merge_layers
from harnessweaver.spec.models import HarnessSpec
from harnessweaver.spec.sources import BuiltinProfiles, ProfileRef, ResolvedProfile

from .test_suites import _strict_equal

_ERRORS: dict[str, type[SpecError]] = {
    "lock_violation": LockViolation,
    "bound_violation": BoundViolation,
    "spec_invalid": SpecError,
}


class _OrgProfiles:
    def __init__(self, documents: dict[str, dict[str, Any]]) -> None:
        self.documents = documents

    def resolve(self, ref: ProfileRef, relative_to: Path | None) -> ResolvedProfile | None:
        if ref.scheme == "org" and ref.name in self.documents:
            document = self.documents[ref.name]
            return ResolvedProfile(f"org://{ref.name}", LayerKind.ORG, document, None, None)
        return None


def _expect_error(expect: dict[str, Any], error: SpecError) -> None:
    expected_type = _ERRORS[expect["error"]]
    if expected_type is SpecError:
        assert type(error) is SpecError, f"expected a plain SpecError, got {type(error).__name__}"
    else:
        assert isinstance(error, expected_type)
    for key in ("lock", "bound"):
        if key in expect:
            assert error.details[key] == expect[key]


def _run_merge(case: dict[str, Any]) -> None:
    layers = [
        Layer(layer["name"], LayerKind(layer["kind"]), layer["data"]) for layer in case["layers"]
    ]
    expect = case["expect"]
    if "error" in expect:
        with pytest.raises(SpecError) as caught:
            merge_layers(layers)
        _expect_error(expect, caught.value)
        return
    merged = merge_layers(layers)
    assert _strict_equal(merged.data, expect["value"]), merged.data
    for path, layer in expect.get("provenance", {}).items():
        assert merged.provenance[path].layer == layer, path


def _run_budget(case: dict[str, Any]) -> None:
    org: dict[str, Any] = {
        "apiVersion": "harnessweaver/v1",
        "kind": "Profile",
        "metadata": {"name": "org", "version": "1.0.0"},
        "budgets": {"per_run": case["per_run"]},
    }
    if "bounds" in case:
        org["bounds"] = case["bounds"]
    app = {
        "apiVersion": "harnessweaver/v1",
        "kind": "Harness",
        "metadata": {"name": "app"},
        "extends": ["org://org"],
        "tasks": {"t": {"budget": case["task_budget"]}},
    }
    effective = spec_from_documents(app, resolvers=[BuiltinProfiles(), _OrgProfiles({"org": org})])
    expect = case["expect"]
    if "error" in expect:
        with pytest.raises(SpecError) as caught:
            effective.run_budget("t", case["overrides"])
        _expect_error(expect, caught.value)
        return
    budget = effective.run_budget("t", case["overrides"])
    assert _strict_equal(budget.model_dump(mode="json"), expect["budget"])


@pytest.mark.conformance_suite("merge")
def test_merge(case: dict[str, Any]) -> None:
    if "layers" in case:
        _run_merge(case)
    else:
        _run_budget(case)


@pytest.mark.conformance_suite("levels")
def test_levels(case: dict[str, Any]) -> None:
    spec = HarnessSpec.model_validate(
        {"metadata": {"name": "app", "risk_tier": case["risk_tier"]}, **case["spec"]}
    )
    report = assess(spec)
    expect = case["expect"]
    assert report.level.value == expect["level"]
    assert report.required.value == expect["required"]
    unmet = {level.value: list(codes) for level, codes in report.unmet.items()}
    assert unmet == expect["unmet"]
