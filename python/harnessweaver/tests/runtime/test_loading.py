"""Load-time checks: names, plugins, bands, reachability and unsupported sections (R4)."""

import json
from pathlib import Path
from typing import Any

import pytest

import harnessweaver as hw
from harnessweaver.core.registry import PluginCatalog, PluginSource
from harnessweaver.errors import (
    LockViolation,
    PluginConflict,
    PluginNotAllowed,
    SpecError,
    UnknownProvider,
    UnreachableHook,
)

from .conftest import Builder, scripted, spec, write

MODELS = scripted({"text": "x"})


def org_profile(tmp_path: Path, **body: Any) -> str:
    directory = tmp_path / ".harness" / "profiles"
    directory.mkdir(parents=True, exist_ok=True)
    document = {
        "apiVersion": "harnessweaver/v1",
        "kind": "Profile",
        "metadata": {"name": "acme-baseline", "version": "1.0.0"},
        **body,
    }
    (directory / "acme-baseline.yaml").write_text(json.dumps(document), encoding="ascii")
    return "org://acme-baseline"


@pytest.mark.parametrize(
    ("section", "value", "named"),
    [
        ("evals", {"online": {"sample_rate": 0.1}}, "evals.online"),
        ("sidecar", {"url": "http://127.0.0.1:7070"}, "sidecar"),
    ],
)
def test_sections_without_a_module_fail_to_load(
    build: Builder, section: str, value: Any, named: str
) -> None:
    with pytest.raises(SpecError, match="doesn't support yet") as caught:
        build(spec(models=MODELS, **{section: value}))
    assert named in caught.value.details["sections"]  # type: ignore[operator]


def test_task_approval_tools_must_exist(build: Builder) -> None:
    task = {"runner": "direct", "approvals": {"tools": ["wire_money"]}}
    with pytest.raises(SpecError, match=r"tasks\.t\.approvals\.tools: no tool named .wire_money."):
        build(spec(models=MODELS, tasks={"t": task}))


def test_an_unknown_approval_channel_fails(build: Builder) -> None:
    with pytest.raises(UnknownProvider, match="slack"):
        build(spec(models=MODELS, approvals={"use": "slack"}))


def test_an_exporter_needs_the_sdk_setup(build: Builder) -> None:
    with pytest.raises(SpecError, match="configure_sdk"):
        build(spec(models=MODELS, observability={"exporter": "otlp"}))
    with pytest.raises(UnknownProvider, match="otel"):
        build(spec(models=MODELS, observability={"configure_sdk": True}))


def test_unknown_names_fail(build: Builder) -> None:
    with pytest.raises(UnknownProvider, match="it provides"):
        build(spec(models={"provider": "testkit.missing"}))
    with pytest.raises(UnknownProvider, match="no installed plugin"):
        build(spec(models={"provider": "acme.chat"}))
    with pytest.raises(UnknownProvider):
        build(spec(models=MODELS, tasks={"t": {"runner": "acme.flow"}}))
    with pytest.raises(UnknownProvider):
        build(spec(models=MODELS, middleware=[{"use": "testkit.nope"}]))
    with pytest.raises(UnknownProvider):
        build(spec(models=MODELS, state={"use": "redis"}))


def test_settings_are_validated(build: Builder) -> None:
    with pytest.raises(SpecError, match="replies"):
        build(spec(models={"provider": "testkit.scripted"}))
    with pytest.raises(SpecError, match="max_steps"):
        build(spec(models=MODELS, tasks={"t": {"runner": {"use": "direct", "max_steps": 0}}}))
    with pytest.raises(SpecError, match="takes no settings"):
        build(spec(models=MODELS, middleware=[{"use": "testkit.audit", "level": 3}]))
    with pytest.raises(SpecError, match="rules"):
        build(spec(models=MODELS, middleware=[{"use": "testkit.script"}]))
    with pytest.raises(SpecError, match="path"):
        build(spec(models=MODELS, state={"use": "sqlite", "path": 3}))


def test_middleware_hooks_can_only_narrow(build: Builder) -> None:
    harness = build(
        spec(models=MODELS, middleware=[{"use": "testkit.audit", "hooks": ["run.start"]}])
    )
    assert [r.name for r in harness.hooks()[hw.HookPoint.RUN_START]] == ["testkit.audit"]
    assert harness.hooks()[hw.HookPoint.RUN_END] == []
    with pytest.raises(SpecError, match="doesn't attach"):
        build(spec(models=MODELS, middleware=[{"use": "testkit.flaky", "hooks": ["run.end"]}]))


def test_disabled_and_repeated_middleware(build: Builder) -> None:
    harness = build(
        spec(
            models=MODELS,
            middleware=[
                {"id": "first", "use": "testkit.audit", "band": "platform"},
                {"id": "second", "use": "testkit.audit", "band": "task"},
                {"use": "testkit.flaky", "enabled": False},
            ],
        )
    )
    chain = harness.hooks()[hw.HookPoint.INPUT_BEFORE]
    assert [(r.name, r.band) for r in chain] == [
        ("testkit.audit[first]", hw.Band.PLATFORM),
        ("testkit.audit[second]", hw.Band.TASK),
    ]


def test_only_profiles_use_the_baseline_band(build: Builder, tmp_path: Path) -> None:
    with pytest.raises(SpecError, match="only profiles"):
        build(spec(models=MODELS, middleware=[{"use": "testkit.audit", "band": "baseline"}]))
    ref = org_profile(
        tmp_path, middleware=[{"id": "open", "use": "testkit.flaky", "band": "baseline"}]
    )
    with pytest.raises(SpecError, match="R2"):
        build(spec(models=MODELS, extends=[ref]))
    ref = org_profile(
        tmp_path,
        middleware=[
            {"id": "open", "use": "testkit.flaky", "band": "baseline", "fail_mode": "closed"}
        ],
    )
    harness = build(spec(models=MODELS, extends=[ref]))
    (registration,) = harness.hooks()[hw.HookPoint.INPUT_BEFORE]
    assert registration.band is hw.Band.BASELINE
    assert registration.fail_mode == "closed"


def test_runners_must_reach_what_the_baseline_needs(build: Builder, tmp_path: Path) -> None:
    partial = {"t": {"runner": "testkit.partial"}}
    assert build(spec(models=MODELS, tasks=partial)).tasks == ["t"]
    ref = org_profile(
        tmp_path, middleware=[{"id": "audit", "use": "testkit.audit", "band": "baseline"}]
    )
    with pytest.raises(UnreachableHook, match=r"tool\.before"):
        build(spec(models=MODELS, extends=[ref], tasks=partial))
    with pytest.raises(UnreachableHook, match=r"tool\.before"):
        build(spec(models=MODELS, budgets={"per_run": {"max_tool_calls": 3}}, tasks=partial))
    model_budget = build(spec(models=MODELS, budgets={"per_run": {"max_usd": 1}}, tasks=partial))
    assert model_budget.tasks == ["t"]


def test_task_references_are_checked(build: Builder) -> None:
    with pytest.raises(SpecError, match=r"needs models\.provider"):
        build(spec(tasks={"t": {"runner": "direct"}}))
    with pytest.raises(SpecError, match="no prompt"):
        build(spec(models=MODELS, tasks={"t": {"runner": "direct", "prompt": "absent@1"}}))
    with pytest.raises(SpecError, match="no tool named"):
        build(spec(models=MODELS, tasks={"t": {"runner": "direct", "tools": ["absent"]}}))
    with pytest.raises(SpecError, match="no tool named"):
        build(
            spec(models=MODELS, tasks={"t": {"runner": "direct", "tools": ["lookup"]}}), tools=None
        )
    with pytest.raises(SpecError, match="can't import"):
        build(
            spec(models=MODELS, tasks={"t": {"runner": "direct", "output": "hw_testkit:Missing"}})
        )
    with pytest.raises(SpecError, match="not a type"):
        build(spec(models=MODELS, tasks={"t": {"runner": "direct", "output": "hw_testkit:answer"}}))


def test_plugins_allow_applies_to_local_plugins(build: Builder) -> None:
    with pytest.raises(PluginNotAllowed):
        build(spec(models=MODELS, plugins={"local": ["hw_testkit"], "allow": ["openai"]}))
    harness = build(spec(models=MODELS, plugins={"local": ["hw_testkit"], "allow": ["testkit"]}))
    assert "testkit" in {p.plugin.namespace for p in harness.registry.plugins()}


def test_plugin_profiles(tmp_path: Path, testkit: Any) -> None:
    catalog = PluginCatalog(
        [PluginSource("testkit", "hw_testkit:plugin", "entry_point", "hw-testkit")]
    )
    document = spec(models=MODELS, extends=["profile://testkit.strict@^1"])
    document["plugins"] = {}
    harness = hw.Harness.load(write(tmp_path, document), catalog=catalog)
    assert harness.spec.spec.budgets.per_run.max_model_calls == 5
    origin = harness.spec.origin("budgets.per_run.max_model_calls")
    assert origin is not None
    assert origin.layer == "profile://testkit.strict@1.2.0"

    locked = {**document, "budgets": {"per_run": {"max_model_calls": 9}}}
    with pytest.raises(LockViolation):
        hw.Harness.load(write(tmp_path, locked), catalog=catalog)
    allowed = {**document, "plugins": {"allow": ["openai"]}}
    with pytest.raises(PluginNotAllowed):
        hw.Harness.load(write(tmp_path, allowed), catalog=catalog)
    missing = {**document, "extends": ["profile://testkit.absent"]}
    with pytest.raises(SpecError, match="has no profile"):
        hw.Harness.load(write(tmp_path, missing), catalog=catalog)
    wrong_version = {**document, "extends": ["profile://testkit.strict@^2"]}
    with pytest.raises(SpecError, match="outside"):
        hw.Harness.load(write(tmp_path, wrong_version), catalog=catalog)
    clash = {**document, "plugins": {"local": ["hw_testkit"]}}
    with pytest.raises(PluginConflict):
        hw.Harness.load(write(tmp_path, clash), catalog=catalog)


def test_load_uses_the_default_catalog(tmp_path: Path, testkit: Any) -> None:
    harness = hw.load(write(tmp_path, spec(models=MODELS)))
    assert harness.name == "test-app"


def test_run_start_rules_may_not_use_the_tool_or_its_arguments(build: Builder) -> None:
    rule = {"id": "big", "when": "args.amount_usd > 100", "effect": "deny", "hook": "run.start"}
    with pytest.raises(SpecError, match=r"policy.rules\[big\].*args"):
        build(spec(models=MODELS, policy={"rules": [rule]}))
