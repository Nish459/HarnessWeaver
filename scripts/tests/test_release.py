"""Tests for scripts/release.py: a release tag names one package at its exact version."""

import pytest
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
