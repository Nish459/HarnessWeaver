"""Tests for scripts/release.py: a release tag names one package at its exact version."""

import json
import re
import subprocess
from pathlib import Path

import pytest
import release
import yaml
from release import ROOT, Package, is_semver, packages, releases

CORE = Package("harnessweaver", "0.2.0", ROOT / "python/harnessweaver/pyproject.toml")
TS_CORE = Package(
    "@harnessweaver/core", "1.0.0-rc.1", ROOT / "typescript/packages/core/package.json"
)
KNOWN = {package.name: package for package in (CORE, TS_CORE)}


def test_every_package_in_the_repository_has_a_semver_version() -> None:
    found = packages()
    assert {"harnessweaver", "harnessweaver-pydantic-ai", "@harnessweaver/ai-sdk"} <= found.keys()
    for package in found.values():
        assert is_semver(package.version), package


def test_upload_sends_what_was_built_without_rebuilding(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # CI attests the artifacts it built, so uploading must not replace them with new ones.
    version = packages()["harnessweaver"].version
    monkeypatch.setattr(release, "OUT", tmp_path)
    (tmp_path / "harnessweaver").mkdir()
    monkeypatch.setattr(
        release, "git", lambda *args: f"harnessweaver@{version}\n" if args[0] == "tag" else ""
    )
    monkeypatch.setattr(release, "build", lambda *args: pytest.fail("rebuilt"))
    uploaded: list[str] = []
    monkeypatch.setattr(release, "upload", lambda package, out: uploaded.append(package.name))
    assert release.main(["upload", "harnessweaver"]) == 0
    assert uploaded == ["harnessweaver"]
    assert (tmp_path / "harnessweaver").is_dir()


def test_upload_refuses_a_package_that_was_not_built(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    version = packages()["harnessweaver"].version
    monkeypatch.setattr(release, "OUT", tmp_path)
    monkeypatch.setattr(
        release, "git", lambda *args: f"harnessweaver@{version}\n" if args[0] == "tag" else ""
    )
    monkeypatch.setattr(release, "upload", lambda *args: pytest.fail("uploaded"))
    assert release.main(["upload", "harnessweaver"]) == 1
    assert "harnessweaver: nothing built" in capsys.readouterr().err


def test_npm_packages_are_published_with_npm(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # npm's own client does the trusted-publishing exchange and adds provenance.
    (tmp_path / "core-1.0.0-rc.1.tgz").touch()
    commands: list[tuple[str | Path, ...]] = []
    monkeypatch.setattr(release, "run", lambda *args: commands.append(args))
    release.upload(TS_CORE, tmp_path)
    assert commands == [
        (
            "npm",
            "publish",
            tmp_path / "core-1.0.0-rc.1.tgz",
            "--access",
            "public",
            "--tag",
            "next",
        )
    ]


def test_npm_packages_name_their_repository() -> None:
    # npm refuses provenance unless repository.url matches the repository that built it.
    for package in packages().values():
        if package.manifest.name == "package.json":
            repository = json.loads(package.manifest.read_text())["repository"]
            assert repository["url"] == "git+https://github.com/Wise-DreamerZ/HarnessWeaver.git"
            assert (ROOT / repository["directory"]) == package.manifest.parent


def test_every_workflow_action_is_pinned_by_commit() -> None:
    # RULES S5: a tag can be moved, so a release must not run whatever a tag now points at.
    for workflow in (ROOT / ".github/workflows").glob("*.yml"):
        for used in re.findall(r"uses:\s*(\S+)", workflow.read_text()):
            assert re.fullmatch(r"[\w.-]+/[\w./-]+@[0-9a-f]{40}", used), (workflow.name, used)


@pytest.mark.parametrize(("secret", "seen"), [("", "unset"), ("pypi-test", "pypi-test")])
def test_the_pypi_token_reaches_uv_only_when_its_secret_is_set(
    tmp_path: Path, secret: str, seen: str
) -> None:
    # uv takes an empty UV_PUBLISH_TOKEN as a token and skips trusted publishing, so the
    # upload step must leave it unset when the release environment has no PYPI_TOKEN.
    workflow = yaml.safe_load((ROOT / ".github/workflows/release.yml").read_text())
    step = next(s for s in workflow["jobs"]["publish"]["steps"] if "env" in s)
    assert step["env"]["PYPI_TOKEN"] == "${{ secrets.PYPI_TOKEN }}"
    assert "UV_PUBLISH_TOKEN" not in step["env"]
    # Run the step's script with a uv that only reports the token it was given.
    fake_uv = tmp_path / "uv"
    fake_uv.write_text('#!/bin/sh\necho "${UV_PUBLISH_TOKEN-unset}"\n')
    fake_uv.chmod(0o755)
    env = {"PATH": f"{tmp_path}:/usr/bin:/bin", "PYPI_TOKEN": secret, "PACKAGES": ""}
    done = subprocess.run(
        ["bash", "-e", "-c", step["run"]], env=env, capture_output=True, text=True, check=True
    )
    assert done.stdout == f"{seen}\n"


def test_every_package_ships_the_license() -> None:
    # Hatchling and pnpm pack each include a LICENSE beside the manifest, and Apache-2.0
    # requires that recipients get a copy.
    license_text = (ROOT / "LICENSE").read_text()
    for package in packages().values():
        assert (package.manifest.parent / "LICENSE").read_text() == license_text, package.name


def test_core_packages_are_released_before_the_packages_that_need_them() -> None:
    otel = Package("harnessweaver-otel", "0.2.0", ROOT / "python/plugins/otel/pyproject.toml")
    ai_sdk = Package(
        "@harnessweaver/ai-sdk", "0.2.0", ROOT / "typescript/packages/ai-sdk/package.json"
    )
    ts_core = Package("@harnessweaver/core", "0.2.0", TS_CORE.manifest)
    known = {package.name: package for package in (CORE, otel, ai_sdk, ts_core)}
    tags = [f"{name}@0.2.0" for name in sorted(known)]
    chosen, problems = releases(tags, known)
    assert problems == []
    assert {package.name for package in chosen[:2]} == {"harnessweaver", "@harnessweaver/core"}


@pytest.mark.parametrize("text", ["0.1.0", "1.0.0-rc.1", "10.20.30-alpha.beta.1"])
def test_semver_versions_are_accepted(text: str) -> None:
    assert is_semver(text)


@pytest.mark.parametrize(
    "text", ["", "1.0", "v1.0.0", "01.0.0", " 1.0.0", "1.0.0-rc.01", "1.0.0+build.5"]
)
def test_other_versions_are_refused(text: str) -> None:
    assert not is_semver(text)


def test_tags_that_match_their_manifests_are_released() -> None:
    assert releases(["harnessweaver@0.2.0", "@harnessweaver/core@1.0.0-rc.1"], KNOWN) == (
        [CORE, TS_CORE],
        [],
    )


@pytest.mark.parametrize(
    ("tag", "problem"),
    [
        ("harnessweaver@0.3.0", "python/harnessweaver/pyproject.toml has version 0.2.0"),
        ("@harnessweaver/core@1.0.0", "typescript/packages/core/package.json has version"),
        ("harnessweaver@v0.2.0", "not a SemVer version"),
        ("harnessweaver@0.2.0+build.1", "not a SemVer version"),
        ("v0.2.0", "not <package>@<version>"),
        ("harnessweaver-otel@0.2.0", "not <package>@<version>"),
    ],
)
def test_a_bad_tag_is_reported_and_not_released(tag: str, problem: str) -> None:
    chosen, problems = releases(["harnessweaver@0.2.0", tag], KNOWN)
    assert chosen == [CORE]
    assert len(problems) == 1
    assert problems[0].startswith(f"{tag}: ")
    assert problem in problems[0]


def test_only_the_named_packages_are_released() -> None:
    tags = ["harnessweaver@0.2.0", "@harnessweaver/core@1.0.0-rc.1", "v0.2.0"]
    assert releases(tags, KNOWN, only=["@harnessweaver/core"]) == ([TS_CORE], [])


def test_a_named_package_needs_its_tag() -> None:
    chosen, problems = releases(["harnessweaver@0.2.0"], KNOWN, only=["@harnessweaver/core"])
    assert chosen == []
    assert problems == ["@harnessweaver/core: HEAD has no @harnessweaver/core@<version> tag"]


def test_a_named_package_still_needs_the_right_version() -> None:
    chosen, problems = releases(["harnessweaver@0.3.0"], KNOWN, only=["harnessweaver"])
    assert chosen == []
    assert problems == [
        "harnessweaver@0.3.0: python/harnessweaver/pyproject.toml has version 0.2.0"
    ]


def test_no_tags_is_a_problem() -> None:
    chosen, problems = releases([], KNOWN)
    assert chosen == []
    assert problems == ["HEAD has no release tags: tag it <package>@<version> first"]
