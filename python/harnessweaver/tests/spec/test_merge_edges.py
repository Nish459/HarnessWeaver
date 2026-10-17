from pathlib import Path
from typing import Any

import pytest

from harnessweaver.core.errors import LockViolation, SpecError
from harnessweaver.spec.explain import explain_rows
from harnessweaver.spec.loader import load_spec, spec_from_documents
from harnessweaver.spec.merge import Layer, LayerKind, merge_layers


def merge(*bodies: tuple[str, dict[Any, Any]]) -> Any:
    kinds = {"org": LayerKind.ORG, "app": LayerKind.APP}
    return merge_layers([Layer(name, kinds[name], body) for name, body in bodies])


def test_type_changes_replace_the_subtree_and_its_provenance() -> None:
    merged = merge(("org", {"x": {"a": 1, "b": 2}}), ("app", {"x": 5}))
    assert merged.data == {"x": 5}
    assert merged.provenance["x"].layer == "app"
    assert "x.a" not in merged.provenance
    rows = explain_rows(merged.data, merged.provenance, merged.locks, merged.bounds)
    assert [(r.path, r.origin.layer if r.origin else None) for r in rows] == [("x", "app")]

    assert merge(("org", {"x": 5}), ("app", {"x": {"a": 1}})).data == {"x": {"a": 1}}


def test_replacing_a_subtree_can_not_hide_a_locked_value() -> None:
    org = {"models": {"base_url": "https://gw"}, "locks": ["models.base_url"]}
    with pytest.raises(LockViolation, match=r"would change models\.base_url"):
        merge(("org", org), ("app", {"models": "fast"}))


@pytest.mark.parametrize(
    ("body", "message"),
    [
        ({1: "a"}, "non-string key"),
        ({"guardrails": {"input": [{"id": 3, "use": "x"}]}}, "non-empty strings"),
        ({"guardrails": {"input": [{"id": "", "use": "x"}]}}, "non-empty strings"),
    ],
)
def test_malformed_app_bodies(body: dict[Any, Any], message: str) -> None:
    with pytest.raises(SpecError, match=message):
        merge(("app", body))


@pytest.mark.parametrize(
    ("org", "message"),
    [
        ({"bounds": ["budgets"]}, "must be a map"),
        ({"bounds": {"a..b": {"max": 1}}}, "invalid spec path"),
        ({"bounds": {"x": {"max": 1, "other": 2}}}, "must have min and/or max"),
        ({"bounds": {"x": {"min": 1, "max": "5m"}}}, "mixes a number and a duration"),
        ({"bounds": {"x": {"max": True}}}, "number or a duration"),
        ({"bounds": {"x": {"max": float("inf")}}}, "must be finite"),
        ({"bounds": {"x": {"max": "soon"}}}, "invalid duration"),
        ({"bounds": {"x": {"max": [1]}}}, "number or a duration"),
        ({"locks": ["a..b"]}, "invalid spec path"),
    ],
)
def test_malformed_locks_and_bounds(org: dict[str, Any], message: str) -> None:
    with pytest.raises(SpecError, match=message):
        merge(("org", org))


def test_bounds_on_items_and_wildcards() -> None:
    org = {
        "guardrails": {"input": [{"id": "g", "use": "x", "threshold": 0.9}]},
        "bounds": {"guardrails.input[*].threshold": {"min": 0.5}},
    }
    merge(("org", org))
    with pytest.raises(SpecError, match="below the minimum"):
        merge(("org", org), ("app", {"guardrails": {"input": [{"id": "g", "threshold": 0.1}]}}))


def _write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return path


APP = "apiVersion: harnessweaver/v1\nkind: Harness\nmetadata: { name: a }\nextends: [ %s ]\n"


@pytest.mark.parametrize(
    ("profile", "ref", "message"),
    [
        ("- not a map\n", "org://p", "is not a map"),
        ("- not a map\n", "./p.yaml", "is not a map"),
        (
            "apiVersion: harnessweaver/v1\nkind: Harness\nmetadata: { name: p }\n",
            "org://p",
            "kind Profile",
        ),
        (
            "apiVersion: harnessweaver/v1\nkind: Profile\nmetadata: { name: p }\nextends: 3\n",
            "org://p",
            "extends in",
        ),
        (
            "apiVersion: harnessweaver/v1\nkind: Profile\nmetadata: { name: p }\n",
            "org://p@^1",
            "can't find",
        ),
    ],
)
def test_bad_profile_documents(tmp_path: Path, profile: str, ref: str, message: str) -> None:
    _write(tmp_path / ".harness" / "profiles" / "p.yaml", profile)
    _write(tmp_path / "p.yaml", profile)
    _write(tmp_path / "harness.yaml", APP % ref)
    with pytest.raises(SpecError, match=message):
        load_spec(tmp_path / "harness.yaml", env="")


def test_unknown_builtin_profile() -> None:
    app = {"apiVersion": "harnessweaver/v1", "kind": "Harness", "metadata": {"name": "a"}}
    with pytest.raises(SpecError, match="can't find profile 'profile://nope'"):
        spec_from_documents({**app, "extends": ["profile://nope"]})


def test_missing_spec_file(tmp_path: Path) -> None:
    with pytest.raises(SpecError, match="can't read"):
        load_spec(tmp_path / "missing.yaml", env="")
