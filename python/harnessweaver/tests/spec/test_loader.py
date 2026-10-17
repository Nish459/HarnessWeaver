from pathlib import Path
from textwrap import dedent

import pytest

from harnessweaver.core.errors import LevelTooLow, LockViolation, SpecError
from harnessweaver.spec.explain import render_diff, render_explain
from harnessweaver.spec.loader import diff_specs, load_spec, spec_from_documents
from harnessweaver.spec.models import Level

HARNESS = "apiVersion: harnessweaver/v1\nkind: Harness\n"
PROFILE = "apiVersion: harnessweaver/v1\nkind: Profile\n"


def write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(dedent(text).lstrip())
    return path


APP = """
    apiVersion: harnessweaver/v1
    kind: Harness
    metadata: {{ name: support, risk_tier: {tier} }}
    extends: [ "org://acme-baseline@^2", "profile://rag" ]
    models: {{ default: fast }}
    tasks:
      answer:
        runner: session
        output: str
        budget: {{ max_usd: 0.10, deadline: 20s, overridable: [max_usd] }}
"""


def org_profile(version: str, max_usd: float = 2.0) -> str:
    return f"""
        apiVersion: harnessweaver/v1
        kind: Profile
        metadata: {{ name: acme-baseline, version: {version} }}
        observability: {{ capture_content: false }}
        require_level: {{ default: L0, tiers: {{ customer_facing: L2 }} }}
        budgets: {{ per_run: {{ max_usd: {max_usd}, deadline: 5m }} }}
        locks: [ observability.capture_content ]
        bounds:
          budgets.per_run.max_usd: {{ max: 5.00 }}
    """


@pytest.fixture
def project(tmp_path: Path) -> Path:
    profiles = tmp_path / ".harness" / "profiles"
    write(profiles / "acme-baseline@2.1.0.yaml", org_profile("2.1.0"))
    write(profiles / "acme-baseline@2.3.0.yaml", org_profile("2.3.0", max_usd=3.0))
    write(profiles / "acme-baseline@3.0.0.yaml", org_profile("3.0.0"))
    write(tmp_path / "harness.yaml", APP.format(tier="internal"))
    return tmp_path


def test_layers_are_ordered_and_the_highest_matching_org_version_wins(project: Path) -> None:
    effective = load_spec(project / "harness.yaml", env="")
    assert [layer.layer for layer in effective.layers] == [
        "profile://defaults",
        "profile://rag",
        "org://acme-baseline@2.3.0",
        "harness.yaml",
    ]
    assert effective.spec.budgets.per_run.max_usd == 3.0
    assert effective.origin("budgets.per_run.max_usd").layer == "org://acme-baseline@2.3.0"  # type: ignore[union-attr]
    assert effective.origin("guardrails.input[rag-pii].use").layer == "profile://rag"  # type: ignore[union-attr]
    assert effective.level.level is Level.L1


def test_environment_overlay_applies_and_is_bound_by_locks(
    project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    write(project / "harness.prod.yaml", "models: { default: strong }\n")
    monkeypatch.setenv("HARNESSWEAVER_ENV", "prod")
    effective = load_spec(project / "harness.yaml")
    assert effective.spec.models.default == "strong"
    assert effective.layers[-1].layer == "harness.prod.yaml"

    write(project / "harness.dev.yaml", "observability: { capture_content: true }\n")
    with pytest.raises(LockViolation, match=r"observability\.capture_content is locked"):
        load_spec(project / "harness.yaml", env="dev")

    # A missing overlay is not an error; the layers show what was applied.
    assert load_spec(project / "harness.yaml", env="staging").layers[-1].layer == "harness.yaml"


def test_profile_search_path_from_the_environment(
    tmp_path: Path, project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    shared = tmp_path / "shared-profiles"
    write(shared / "acme-baseline.yaml", org_profile("2.9.0"))
    monkeypatch.setenv("HARNESSWEAVER_PROFILE_PATH", str(shared))
    effective = load_spec(project / "harness.yaml", env="")
    assert "org://acme-baseline@2.9.0" in [layer.layer for layer in effective.layers]


def test_required_level_is_enforced_at_load(project: Path) -> None:
    write(project / "harness.yaml", APP.format(tier="customer_facing"))
    with pytest.raises(LevelTooLow, match="requires L2") as caught:
        load_spec(project / "harness.yaml", env="")
    assert caught.value.details["missing"] == ["L2.policy_rules"]


def test_errors_name_the_layer_that_set_the_bad_value(project: Path) -> None:
    write(project / "harness.qa.yaml", "tasks: { answer: { budget: { max_usd: -1 } } }\n")
    with pytest.raises(SpecError, match=r"tasks.answer.budget.max_usd: .* \(from harness.qa.yaml"):
        load_spec(project / "harness.yaml", env="qa")


@pytest.mark.parametrize(
    ("document", "message"),
    [
        ("kind: Harness\nmetadata: { name: a }\n", "apiVersion must be"),
        (
            "apiVersion: harnessweaver/v1\nkind: Profile\nmetadata: { name: a }\n",
            "kind must be 'Harness'",
        ),
        ("apiVersion: harnessweaver/v1\nkind: Harness\n", "metadata"),
        (
            "apiVersion: harnessweaver/v1\nkind: Harness\nmetadata: { name: a }\nguards: {}\n",
            "unknown or misplaced key",
        ),
        (
            "apiVersion: harnessweaver/v1\nkind: Harness\nmetadata: { name: a }\nlocks: [x]\n",
            "unknown or misplaced key",
        ),
        (
            "apiVersion: harnessweaver/v1\nkind: Harness\nmetadata: { name: a }\nextends: 3\n",
            "extends must be a list",
        ),
        ("- just\n- a list\n", "must be a YAML map"),
        (
            HARNESS + "metadata: { name: a }\nmetadata: { name: b }\n",
            "duplicate key",
        ),
    ],
)
def test_malformed_documents(tmp_path: Path, document: str, message: str) -> None:
    write(tmp_path / "harness.yaml", document)
    with pytest.raises(SpecError, match=message):
        load_spec(tmp_path / "harness.yaml", env="")


def test_overlays_can_only_hold_sections(tmp_path: Path) -> None:
    write(
        tmp_path / "harness.yaml",
        "apiVersion: harnessweaver/v1\nkind: Harness\nmetadata: { name: a }\n",
    )
    write(tmp_path / "harness.prod.yaml", "metadata: { name: b }\n")
    with pytest.raises(SpecError, match="unknown or misplaced key"):
        load_spec(tmp_path / "harness.yaml", env="prod")


def _app(**body: object) -> dict[str, object]:
    return {"apiVersion": "harnessweaver/v1", "kind": "Harness", "metadata": {"name": "a"}, **body}


def test_unknown_profiles_cycles_and_versions(tmp_path: Path) -> None:
    with pytest.raises(SpecError, match="can't find profile 'org://nope'"):
        spec_from_documents(_app(extends=["org://nope"]))
    with pytest.raises(SpecError, match="outside \\^2"):
        spec_from_documents(_app(extends=["profile://rag@^2"]))
    profile = (
        "apiVersion: harnessweaver/v1\nkind: Profile\nmetadata: {{ name: {n} }}\nextends: [ {p} ]\n"
    )
    write(tmp_path / "a.yaml", profile.format(n="a", p="./b.yaml"))
    write(tmp_path / "b.yaml", profile.format(n="b", p="./a.yaml"))
    write(
        tmp_path / "harness.yaml",
        HARNESS + "metadata: { name: x }\nextends: [ ./a.yaml ]\n",
    )
    with pytest.raises(SpecError, match="cycle"):
        load_spec(tmp_path / "harness.yaml", env="")


def test_file_profiles_and_their_parents(tmp_path: Path) -> None:
    write(
        tmp_path / "team.yaml",
        PROFILE
        + "metadata: { name: team }\nextends: [ profile://agent ]\nmodels: { default: fast }\n",
    )
    write(
        tmp_path / "harness.yaml",
        HARNESS + "metadata: { name: x }\nextends: [ ./team.yaml ]\n",
    )
    effective = load_spec(tmp_path / "harness.yaml", env="")
    assert [layer.layer for layer in effective.layers] == [
        "profile://defaults",
        "profile://agent",
        "./team.yaml",
        "harness.yaml",
    ]


def test_rules_are_compiled_at_load() -> None:
    bad_policy = _app(policy={"rules": [{"id": "r", "when": "argz.amount > 1", "effect": "deny"}]})
    with pytest.raises(SpecError, match=r"policy.rules\[r\].when: undeclared reference 'argz'"):
        spec_from_documents(bad_policy)
    bad_validation = _app(validation={"rules": [{"when": "output.total >", "message": "m"}]})
    with pytest.raises(SpecError, match=r"validation.rules\[rule#1\].when"):
        spec_from_documents(bad_validation)


def test_only_profiles_may_use_the_baseline_band() -> None:
    with pytest.raises(SpecError, match="only profiles may put middleware in the baseline band"):
        spec_from_documents(_app(middleware=[{"id": "m", "use": "acme.trace", "band": "baseline"}]))


def test_run_budget_rejects_unknown_tasks() -> None:
    with pytest.raises(SpecError, match="unknown task"):
        spec_from_documents(_app()).run_budget("nope")


def test_explain_shows_layers_locks_and_bounds(project: Path) -> None:
    text = render_explain(load_spec(project / "harness.yaml", env="").explain())
    assert "observability.capture_content" in text
    assert "[locked by org://acme-baseline@2.3.0]" in text
    assert "budgets.per_run.max_usd" in text
    assert "[max 5]" in text
    assert "<- harness.yaml" in text


def test_diff_shows_value_lock_and_level_changes(project: Path) -> None:
    before = load_spec(project / "harness.yaml", env="")
    write(
        project / "harness.yaml",
        APP.format(tier="internal").replace("default: fast", "default: strong"),
    )
    after = load_spec(project / "harness.yaml", env="")
    diff = diff_specs(before, after)
    assert [(c.path, c.kind, c.before, c.after) for c in diff.changes] == [
        ("models.default", "changed", "fast", "strong")
    ]
    assert '| `models.default` | changed | `"fast"` | `"strong"` |' in render_diff(diff)
    assert render_diff(diff_specs(before, before)) == "No changes to the effective spec."
