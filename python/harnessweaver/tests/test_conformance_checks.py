"""The conformance checks catch what they promise to catch (RULES T5)."""

import sys
from pathlib import Path
from types import ModuleType

import pytest

from harnessweaver.core.plugins import Plugin
from harnessweaver.core.registry import LoadedPlugin, PluginSource
from harnessweaver.testing import conformance
from harnessweaver.testing.conformance import Subject

FIXTURES = Path(__file__).resolve().parent / "fixtures"


@pytest.fixture
def badkit(monkeypatch: pytest.MonkeyPatch) -> LoadedPlugin:
    monkeypatch.syspath_prepend(str(FIXTURES))
    return conformance.load_plugin("hw_badkit:plugin")


def subject(loaded: LoadedPlugin, name: str) -> Subject:
    return next(s for s in conformance.subjects(loaded) if s.name == name)


def test_the_built_in_plugin_passes_the_plugin_checks() -> None:
    builtin = conformance.load_plugin("harnessweaver")
    conformance.check_plugin(builtin)
    conformance.check_import_is_inert("harnessweaver.builtins")
    assert {s.name for s in conformance.subjects(builtin)} >= {"direct", "pii.regex", "sqlite"}


def test_plugin_metadata_problems(badkit: LoadedPlugin) -> None:
    with pytest.raises(AssertionError, match="no_such_profile"):
        conformance.check_plugin(badkit)
    with pytest.raises(AssertionError, match=r"^\S+ is not a harnessweaver\.Plugin"):
        conformance.load_plugin("hw_badkit:LeakyGuard")


def test_import_side_effects_are_caught(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PYTHONPATH", f"{FIXTURES}:{':'.join(sys.path)}")
    with pytest.raises(AssertionError, match="files created"):
        conformance.check_import_is_inert("hw_noisy")
    with pytest.raises(AssertionError, match="failed"):
        conformance.check_import_is_inert("hw_does_not_exist")


def test_a_provider_without_settings_doesnt_build(badkit: LoadedPlugin) -> None:
    with pytest.raises(AssertionError, match="declare sample"):
        conformance.check_builds(subject(badkit, "badkit.needy"))
    conformance.check_builds(subject(badkit, "badkit.leaky"))
    conformance.check_builds(subject(badkit, "badkit.unsampled"))


@pytest.mark.anyio
async def test_wrong_results_are_caught(badkit: LoadedPlugin) -> None:
    with pytest.raises(AssertionError, match="returned dict"):
        await conformance.check_results(subject(badkit, "badkit.wrong"))
    await conformance.check_results(subject(badkit, "badkit.leaky"))


@pytest.mark.anyio
async def test_a_sandbox_that_lets_code_out_is_caught(badkit: LoadedPlugin) -> None:
    with pytest.raises(AssertionError, match="read a host file"):
        await conformance.check_results(subject(badkit, "badkit.open_sandbox"))


@pytest.mark.anyio
async def test_non_determinism_is_caught(badkit: LoadedPlugin) -> None:
    with pytest.raises(AssertionError, match="differently"):
        await conformance.check_deterministic(subject(badkit, "badkit.moody"))


@pytest.mark.anyio
async def test_leaked_content_is_caught(badkit: LoadedPlugin) -> None:
    with pytest.raises(AssertionError, match="raw content leaked"):
        await conformance.check_no_raw_content(subject(badkit, "badkit.leaky"))
    with pytest.raises(AssertionError):
        await conformance.check_no_raw_content(subject(badkit, "badkit.chatty"))


@pytest.mark.anyio
async def test_slowness_is_caught(badkit: LoadedPlugin) -> None:
    with pytest.raises(AssertionError, match="p95"):
        await conformance.check_latency(subject(badkit, "badkit.slow"), runs=3)


@pytest.mark.anyio
async def test_a_slow_guard_still_blocks_on_timeout(badkit: LoadedPlugin) -> None:
    await conformance.check_timeout_blocks(subject(badkit, "badkit.leaky"))


@pytest.mark.anyio
async def test_bad_middleware_runners_and_adapters_are_caught(badkit: LoadedPlugin) -> None:
    with pytest.raises(AssertionError, match=r"answered input\.before with str"):
        await conformance.check_middleware(subject(badkit, "badkit.confused"))
    with pytest.raises(AssertionError, match="undeclared hooks"):
        await conformance.check_runner(subject(badkit, "badkit.sneaky"))
    with pytest.raises(AssertionError, match="needs sample"):
        await conformance.check_adapter(subject(badkit, "badkit.unsampled"))
    with pytest.raises(AssertionError, match="didn't fire"):
        await conformance.check_adapter(subject(badkit, "badkit.quiet"))


def test_which_checks_apply(badkit: LoadedPlugin) -> None:
    leaky = subject(badkit, "badkit.leaky")
    assert conformance.applies("timeout", leaky)
    assert not conformance.applies("runner", leaky)
    needy = subject(badkit, "badkit.needy")
    assert not conformance.applies("deterministic", needy)
    assert conformance.applies("adapter", subject(badkit, "badkit.quiet"))
    assert Subject(badkit, leaky.contribution).spec() == {
        "plugins": {"local": ["hw_badkit:plugin"]}
    }
    plain = LoadedPlugin(
        Plugin(namespace="x", version="1.0.0"), PluginSource("x", "x:plugin", "entry_point")
    )
    assert Subject(plain, leaky.contribution).spec(tasks={}) == {"tasks": {}}


def test_the_pytest_option_runs_the_suite(
    pytester: pytest.Pytester, testkit_path: ModuleType
) -> None:
    passing = pytester.runpytest_subprocess(
        "--harnessweaver-conformance=harnessweaver", "-q", "-p", "no:cacheprovider"
    )
    passing.assert_outcomes(passed=143)
    failing = pytester.runpytest_subprocess(
        "--harnessweaver-conformance=hw_badkit:plugin", "-q", "-p", "no:cacheprovider"
    )
    outcomes = failing.parseoutcomes()
    assert outcomes["failed"] >= 8
    failing.stdout.fnmatch_lines(["*results*badkit.wrong*"])


@pytest.fixture
def testkit_path(monkeypatch: pytest.MonkeyPatch) -> ModuleType:
    monkeypatch.setenv("PYTHONPATH", f"{FIXTURES}:{':'.join(sys.path)}")
    return sys.modules[__name__]
