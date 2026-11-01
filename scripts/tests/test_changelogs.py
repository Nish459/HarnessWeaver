"""Tests that every package records its releases in its own changelog (RULES D1, V1)."""

from release import packages


def test_every_package_has_a_changelog_entry_for_its_version() -> None:
    for package in packages().values():
        changelog = (package.manifest.parent / "CHANGELOG.md").read_text()
        assert "## [Unreleased]" in changelog, package.name
        assert f"\n## {package.version} - " in changelog, package.name
