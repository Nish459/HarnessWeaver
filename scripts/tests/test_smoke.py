"""Tests for scripts/smoke.py: every package is tried as users get it, after each release."""

import subprocess
import sys
from pathlib import Path

import pytest
import smoke
import yaml
from release import ROOT, Package, packages

PYTHON_PACKAGES = [name for name, p in packages().items() if p.manifest.name == "pyproject.toml"]


def record_tries(monkeypatch: pytest.MonkeyPatch, tags: str, failing: str = "") -> dict[str, str]:
    """Replace the registry installs with a log of the version each package was tried at.

    Args:
        monkeypatch: The test's monkeypatch.
        tags: What ``git tag --points-at HEAD`` prints.
        failing: A package whose smoke test fails.

    Returns:
        Each package tried, in order, and its version (``latest`` for none).
    """
    monkeypatch.setattr(smoke, "git", lambda *args: tags)
    tried: dict[str, str] = {}

    def fake_smoke(package: Package, version: str | None) -> bool:
        tried[package.name] = version or "latest"
        return package.name != failing

    monkeypatch.setattr(smoke, "smoke", fake_smoke)
    return tried


def test_every_package_has_a_smoke_check() -> None:
    # A new package needs a way to be tried, or a release would publish it untried.
    assert smoke.CHECKS.keys() == packages().keys()


def test_the_release_workflow_smoke_tests_what_it_published() -> None:
    workflow = yaml.safe_load((ROOT / ".github/workflows/release.yml").read_text())
    job = workflow["jobs"]["smoke"]
    assert job["needs"] == "publish"
    step = next(s for s in job["steps"] if "smoke.py" in s.get("run", ""))
    # The input stays in the environment, as for the upload, and is never pasted into code.
    assert step["env"]["PACKAGES"] == "${{ inputs.packages }}"
    assert step["run"].endswith("python scripts/smoke.py $PACKAGES")


def test_tagged_packages_are_tried_at_their_tag_and_the_rest_at_the_latest(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tried = record_tries(monkeypatch, "harnessweaver@0.19.0\n@harnessweaver/core@1.0.0-rc.1\nv1\n")
    assert smoke.main([]) == 0
    assert tried.keys() == packages().keys()
    assert tried["harnessweaver"] == "0.19.0"
    assert tried["@harnessweaver/core"] == "1.0.0-rc.1"
    assert tried["harnessweaver-cli"] == "latest"


def test_only_the_named_packages_are_tried(monkeypatch: pytest.MonkeyPatch) -> None:
    tried = record_tries(monkeypatch, "harnessweaver@0.19.0\nharnessweaver-cli@0.8.0\n")
    assert smoke.main(["harnessweaver-cli", "@harnessweaver/ai-sdk"]) == 0
    assert tried == {"harnessweaver-cli": "0.8.0", "@harnessweaver/ai-sdk": "latest"}


def test_a_failure_fails_the_run_once_every_package_is_tried(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    tried = record_tries(monkeypatch, "", failing="harnessweaver-otel")
    assert smoke.main([]) == 1
    assert tried.keys() == packages().keys()
    assert "FAILED  harnessweaver-otel latest" in capsys.readouterr().out


def test_an_unknown_package_is_a_usage_error(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    tried = record_tries(monkeypatch, "")
    assert smoke.main(["harnessweaver-nope"]) == 2
    assert tried == {}
    assert "harnessweaver-nope" in capsys.readouterr().err


def test_an_install_is_retried_until_the_registry_serves_the_version(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # PyPI and npm can take minutes to serve a version they have just been sent.
    codes = iter([1, 1, 0])
    monkeypatch.setattr(
        smoke.subprocess,
        "run",
        lambda args, **kwargs: subprocess.CompletedProcess(args, next(codes)),
    )
    slept: list[float] = []
    monkeypatch.setattr(smoke.time, "sleep", slept.append)
    assert smoke.install(["uv", "pip", "install", "harnessweaver==0.19.0"], Path())
    assert slept == [smoke.DELAY, smoke.DELAY]


def test_an_install_fails_once_its_attempts_run_out(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[object] = []
    monkeypatch.setattr(
        smoke.subprocess,
        "run",
        lambda args, **kwargs: calls.append(args) or subprocess.CompletedProcess(args, 1),
    )
    monkeypatch.setattr(smoke.time, "sleep", lambda seconds: None)
    assert not smoke.install(["npm", "install", "@harnessweaver/core@9.9.9"], Path())
    assert len(calls) == smoke.ATTEMPTS


@pytest.mark.parametrize("name", PYTHON_PACKAGES)
def test_the_python_checks_pass_against_this_checkout(name: str, tmp_path: Path) -> None:
    # The commands a release runs on what it published, run here on the workspace's own
    # install, offline, so a broken check is found before a release depends on it.
    assert smoke.run_checks(name, Path(sys.executable).parent, tmp_path)
