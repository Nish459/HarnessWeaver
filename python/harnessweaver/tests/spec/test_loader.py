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


# -- who owns a profile: an app can't get ahead of, or replace, its platform's baseline ----------

BASELINE = PROFILE + (
    "metadata: {{ name: acme-baseline, version: {version} }}\n"
    "guardrails: {{ input: [ {{ id: base-pii, use: pii.regex, action: redact }} ] }}\n"
    "locks: [ observability.capture_content, 'guardrails.input[base-pii]' ]\n"
)


def _platform(tmp_path: Path, version: str = "1.1.0") -> Path:
    directory = tmp_path / "platform"
    write(directory / "acme-baseline.yaml", BASELINE.format(version=version))
    return directory


def _spec(tmp_path: Path, extends: str, body: str = "") -> Path:
    return write(
        tmp_path / "app" / "harness.yaml",
        HARNESS + f"metadata: {{ name: x }}\nextends: {extends}\n{body}",
    )


def test_an_app_copy_cant_outrank_the_platforms_profile(tmp_path: Path) -> None:
    platform = _platform(tmp_path)
    path = _spec(
        tmp_path, '[ "org://acme-baseline@^1" ]', "observability: { capture_content: true }\n"
    )
    write(
        tmp_path / "app" / ".harness" / "profiles" / "acme-baseline.yaml",
        PROFILE + "metadata: { name: acme-baseline, version: 1.99.0 }\n",
    )
    with pytest.raises(LockViolation):
        load_spec(path, env="", profile_dirs=[platform])


def test_narrowing_the_range_doesnt_fall_through_to_an_app_copy(tmp_path: Path) -> None:
    platform = _platform(tmp_path)
    path = _spec(tmp_path, '[ "org://acme-baseline@^1.2" ]')
    write(
        tmp_path / "app" / ".harness" / "profiles" / "acme-baseline.yaml",
        PROFILE + "metadata: { name: acme-baseline, version: 1.99.0 }\n",
    )
    with pytest.raises(SpecError, match="can't find profile"):
        load_spec(path, env="", profile_dirs=[platform])


def test_the_highest_version_in_the_owning_directory_wins(tmp_path: Path) -> None:
    platform = _platform(tmp_path)
    write(platform / "acme-baseline@1.2.0.yaml", BASELINE.format(version="1.2.0"))
    path = _spec(tmp_path, '[ "org://acme-baseline@^1" ]')
    effective = load_spec(path, env="", profile_dirs=[platform])
    assert effective.layers[1].layer == "org://acme-baseline@1.2.0"


@pytest.mark.parametrize(
    ("reference", "file"),
    [("./pre.yaml", "pre.yaml"), ("org://pre", ".harness/profiles/pre.yaml")],
)
def test_app_profiles_merge_after_the_platforms(tmp_path: Path, reference: str, file: str) -> None:
    platform = _platform(tmp_path)
    path = _spec(tmp_path, f'[ "{reference}", "org://acme-baseline@^1" ]')
    write(
        tmp_path / "app" / file,
        PROFILE
        + "metadata: { name: pre }\n"
        + "guardrails: { input: [ { id: base-pii, enabled: false } ] }\n",
    )
    with pytest.raises(LockViolation, match="base-pii"):
        load_spec(path, env="", profile_dirs=[platform])


def test_a_file_named_by_an_app_profile_is_the_apps_too(tmp_path: Path) -> None:
    platform = _platform(tmp_path)
    path = _spec(tmp_path, '[ "./team.yaml", "org://acme-baseline@^1" ]')
    write(
        tmp_path / "app" / "team.yaml", PROFILE + "metadata: {name: t}\nextends: [ ./pre.yaml ]\n"
    )
    write(tmp_path / "app" / "pre.yaml", PROFILE + "metadata: {name: p}\nmodels: {default: fast}\n")
    effective = load_spec(path, env="", profile_dirs=[platform])
    assert [layer.layer for layer in effective.layers[1:]] == [
        "org://acme-baseline@1.1.0",
        "./pre.yaml",
        "./team.yaml",
        "harness.yaml",
    ]


def test_a_platform_profiles_file_parent_stays_the_platforms(tmp_path: Path) -> None:
    platform = tmp_path / "platform"
    write(
        platform / "acme-baseline.yaml",
        PROFILE + "metadata: { name: acme-baseline, version: 1.0.0 }\nextends: [ common.yaml ]\n",
    )
    write(
        platform / "common.yaml",
        PROFILE
        + "metadata: { name: common }\n"
        + "guardrails: { input: [ { id: base-pii, use: pii.regex } ] }\n"
        + "locks: [ 'guardrails.input[base-pii]' ]\n",
    )
    path = _spec(tmp_path, '[ "./pre.yaml", "org://acme-baseline@^1" ]')
    write(
        tmp_path / "app" / "pre.yaml",
        PROFILE
        + "metadata: { name: pre }\n"
        + "guardrails: { input: [ { id: base-pii, enabled: false } ] }\n",
    )
    with pytest.raises(LockViolation, match="base-pii"):
        load_spec(path, env="", profile_dirs=[platform])


def test_the_same_file_named_by_the_app_and_the_platform_is_the_platforms(tmp_path: Path) -> None:
    platform = tmp_path / "platform"
    write(
        platform / "acme-baseline.yaml",
        PROFILE + "metadata: { name: acme-baseline, version: 1.0.0 }\nextends: [ common.yaml ]\n",
    )
    write(
        platform / "common.yaml",
        PROFILE
        + "metadata: { name: common }\n"
        + "guardrails: { input: [ { id: base-pii, use: pii.regex } ] }\n",
    )
    path = _spec(tmp_path, '[ "./pre.yaml", "../platform/common.yaml", "org://acme-baseline@^1" ]')
    write(tmp_path / "app" / "pre.yaml", PROFILE + "metadata: { name: pre }\n")
    effective = load_spec(path, env="", profile_dirs=[platform])
    assert [layer.layer for layer in effective.layers[1:]] == [
        "common.yaml",
        "org://acme-baseline@1.0.0",
        "./pre.yaml",
        "harness.yaml",
    ]


def test_an_app_file_with_the_same_text_keeps_the_platforms_parent(tmp_path: Path) -> None:
    platform = tmp_path / "platform"
    write(
        platform / "acme-baseline.yaml",
        PROFILE + "metadata: { name: acme-baseline, version: 1.0.0 }\nextends: [ common.yaml ]\n",
    )
    write(
        platform / "common.yaml",
        PROFILE
        + "metadata: { name: common }\n"
        + "observability: { capture_content: false }\n"
        + "locks: [ observability.capture_content ]\n",
    )
    path = _spec(
        tmp_path,
        '[ "common.yaml", "org://acme-baseline@^1" ]',
        "observability: { capture_content: true }\n",
    )
    write(tmp_path / "app" / "common.yaml", PROFILE + "metadata: { name: decoy }\n")
    with pytest.raises(LockViolation, match="capture_content"):
        load_spec(path, env="", profile_dirs=[platform])


def test_same_reference_text_in_another_directory_is_not_a_cycle(tmp_path: Path) -> None:
    write(
        tmp_path / "a" / "x.yaml",
        PROFILE + "metadata: { name: a }\nextends: [ ../b/x.yaml ]\n",
    )
    write(tmp_path / "b" / "x.yaml", PROFILE + "metadata: { name: b }\n")
    write(
        tmp_path / "harness.yaml",
        HARNESS + "metadata: { name: x }\nextends: [ a/x.yaml, b/x.yaml ]\n",
    )
    effective = load_spec(tmp_path / "harness.yaml", env="")
    assert [layer.layer for layer in effective.layers[1:]] == [
        "../b/x.yaml",
        "a/x.yaml",
        "harness.yaml",
    ]


# -- a locked guard that runs on the sidecar is only as fixed as sidecar.url ---------------------

_REMOTE = (
    "sidecar: {{ url: 'http://127.0.0.1:7070' }}\n"
    "guardrails: {{ input: [ {{ id: pii, use: acme.pii, where: sidecar{extra} }} ] }}\n"
    "locks: [ {locks} ]\n"
)


@pytest.mark.parametrize(
    ("extra", "locks", "fails"),
    [
        ("", "'guardrails.input[pii]'", True),
        ("", "'guardrails.input[*]'", True),
        ("", "'guardrails.input[pii].enabled'", True),
        ("", "'guardrails.input[pii]', sidecar.url", False),
        ("", "'guardrails.input[pii]', sidecar", False),
        ("", "models", False),  # an unlocked guard could just be switched off
        (", enabled: false", "'guardrails.input[pii]'", False),
    ],
)
def test_a_locked_sidecar_guard_needs_sidecar_url_locked(
    tmp_path: Path, extra: str, locks: str, fails: bool
) -> None:
    platform = tmp_path / "platform"
    write(
        platform / "base.yaml",
        PROFILE
        + "metadata: { name: base, version: 1.0.0 }\n"
        + _REMOTE.format(extra=extra, locks=locks),
    )
    path = _spec(tmp_path, '[ "org://base@^1" ]')
    if fails:
        with pytest.raises(SpecError, match=r"sidecar\.url"):
            load_spec(path, env="", profile_dirs=[platform])
    else:
        load_spec(path, env="", profile_dirs=[platform])


def test_a_locked_task_guard_on_the_sidecar_needs_the_lock_too(tmp_path: Path) -> None:
    platform = tmp_path / "platform"
    write(
        platform / "base.yaml",
        PROFILE
        + "metadata: { name: base, version: 1.0.0 }\n"
        + "sidecar: { url: 'http://127.0.0.1:7070' }\n"
        + "tasks: { t: { guardrails: { input: [ { id: g, use: acme.pii, where: sidecar } ] } } }\n"
        + "locks: [ 'tasks.t.guardrails.input[g]' ]\n",
    )
    path = _spec(tmp_path, '[ "org://base@^1" ]')
    with pytest.raises(SpecError, match=r"sidecar\.url"):
        load_spec(path, env="", profile_dirs=[platform])


def test_diff_names_a_substituted_layer(tmp_path: Path) -> None:
    write(tmp_path / "team.yaml", PROFILE + "metadata: { name: t }\n")
    write(tmp_path / "other.yaml", PROFILE + "metadata: { name: o }\n")
    write(tmp_path / "a.yaml", HARNESS + "metadata: { name: x }\nextends: [ ./team.yaml ]\n")
    write(tmp_path / "b.yaml", HARNESS + "metadata: { name: x }\nextends: [ ./other.yaml ]\n")
    diff = diff_specs(
        load_spec(tmp_path / "a.yaml", env=""), load_spec(tmp_path / "b.yaml", env="")
    )
    assert not diff.empty
    assert diff.layers_removed == ("./team.yaml",)
    assert diff.layers_added == ("./other.yaml",)
    assert "Layer removed: `./team.yaml`" in render_diff(diff)
