"""Build and publish the packages that the release tags on HEAD name.

A release tag is ``<package>@<version>``: a package's registry name and its SemVer
version, such as ``harnessweaver@0.2.0`` or ``@harnessweaver/core@0.2.0``. Each tag
releases one package, and that package's ``pyproject.toml`` or ``package.json`` must
have exactly that version, because every package is versioned on its own (RULES V1).
Python packages go to PyPI with ``uv publish``, TypeScript packages to npm with
``pnpm publish``.

Usage::

    python scripts/release.py build [PACKAGE ...]     # check the tags, build into dist/release/
    python scripts/release.py publish [PACKAGE ...]   # the same, then upload what was built

Naming packages releases just those, from their tags on HEAD, and leaves the other
tags alone; with no names, every tag on HEAD is released.

Nothing is built unless every tag on HEAD is valid, and nothing is uploaded from a
working tree with changes, so what is published is exactly the tagged commit.
"""

import json
import shutil
import subprocess
import sys
import tomllib
from dataclasses import dataclass
from pathlib import Path

from harnessweaver.core.semver import Version

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "dist" / "release"


@dataclass(frozen=True)
class Package:
    """A package the repository publishes.

    Attributes:
        name: Its name on the registry.
        version: The version in its manifest.
        manifest: Its ``pyproject.toml`` (PyPI) or ``package.json`` (npm).
    """

    name: str
    version: str
    manifest: Path


def packages() -> dict[str, Package]:
    """Find every publishable package: the uv workspace members and the public pnpm packages."""
    found: dict[str, Package] = {}
    root = tomllib.loads((ROOT / "pyproject.toml").read_text())
    for pattern in root["tool"]["uv"]["workspace"]["members"]:
        for manifest in sorted(ROOT.glob(f"{pattern}/pyproject.toml")):
            project = tomllib.loads(manifest.read_text())["project"]
            found[project["name"]] = Package(project["name"], project["version"], manifest)
    for manifest in sorted(ROOT.glob("typescript/packages/*/package.json")):
        data = json.loads(manifest.read_text())
        if not data.get("private"):
            found[data["name"]] = Package(data["name"], data["version"], manifest)
    return found


def is_semver(text: str) -> bool:
    """Whether ``text`` is a SemVer version, written exactly as it parses.

    Build metadata (``+build.5``) is refused too: npm drops it and PyPI refuses it, so
    the published version would not be the tagged one.
    """
    try:
        return str(Version.parse(text)) == text
    except ValueError:
        return False


def releases(
    tags: list[str], known: dict[str, Package], only: list[str] | None = None
) -> tuple[list[Package], list[str]]:
    """Match release tags to packages, checking each tag's version against its manifest.

    Args:
        tags: The tags on the commit to release.
        known: The publishable packages, by name.
        only: Release just these packages, each of which still needs its tag; the tags of
            other packages are left alone. None (or empty) releases every tag.

    Returns:
        The packages to release, and the problems found. Release only when there are none.
    """
    # The last "@" splits the version off, so a scoped npm name keeps its own "@".
    named = {tag: tag.rpartition("@")[0] for tag in tags}
    problems: list[str] = []
    if only:
        tags = [tag for tag in tags if named[tag] in only]
        problems = [
            f"{name}: HEAD has no {name}@<version> tag"
            for name in only
            if name not in {named[tag] for tag in tags}
        ]
    elif not tags:
        return [], ["HEAD has no release tags: tag it <package>@<version> first"]
    chosen: list[Package] = []
    for tag in tags:
        name, _, version = tag.rpartition("@")
        package = known.get(name)
        if package is None:
            problems.append(f"{tag}: not <package>@<version> for one of {', '.join(sorted(known))}")
        elif not is_semver(version):
            problems.append(f"{tag}: {version!r} is not a SemVer version like 1.2.3 or 1.2.3-rc.1")
        elif version != package.version:
            where = package.manifest.relative_to(ROOT)
            problems.append(f"{tag}: {where} has version {package.version}")
        else:
            chosen.append(package)
    return chosen, problems


def git(*args: str) -> str:
    """Run a git command in the repository and return its output."""
    return subprocess.run(
        ["git", *args], cwd=ROOT, check=True, capture_output=True, text=True
    ).stdout


def run(*args: str | Path) -> None:
    """Run a build or publish command in the repository, failing the release if it fails."""
    subprocess.run(args, cwd=ROOT, check=True)


def build(package: Package, out: Path) -> None:
    """Build one package's artifacts into ``out``: an sdist and a wheel, or an npm tarball."""
    if package.manifest.name == "pyproject.toml":
        # --no-sources builds it as anyone outside the workspace would (uv's advice for publishing).
        run("uv", "build", "--package", package.name, "--no-sources", "--out-dir", out)
        return
    # tsc never removes old output, so start from an empty dist/; "name..." also builds
    # the workspace packages it depends on, whose types it compiles against.
    shutil.rmtree(package.manifest.parent / "dist", ignore_errors=True)
    run("pnpm", "-C", "typescript", "--filter", f"{package.name}...", "run", "build")
    run("pnpm", "-C", "typescript", "--filter", package.name, "pack", "--pack-destination", out)


def upload(package: Package, out: Path) -> None:
    """Upload one package's built artifacts to its registry."""
    if package.manifest.name == "pyproject.toml":
        # Credentials: UV_PUBLISH_TOKEN, or trusted publishing on CI.
        # uv picks the sdist and wheel out of the folder (uv build also writes a .gitignore).
        run("uv", "publish", out / "*")
        return
    # Credentials: the npm login in ~/.npmrc. A prerelease goes to the "next" dist-tag,
    # so `npm install` keeps getting the latest release. A tag checkout is a detached
    # HEAD, which pnpm's branch check refuses; main() has already checked the tree.
    dist_tag = ["--tag", "next"] if "-" in package.version else []
    for tarball in sorted(out.glob("*.tgz")):
        run("pnpm", "publish", tarball, "--access", "public", "--no-git-checks", *dist_tag)


def main(argv: list[str]) -> int:
    """Check the release tags on HEAD, then build (and, for ``publish``, upload) each package.

    Args:
        argv: ``build`` or ``publish``, then optionally the names of the packages to release.

    Returns:
        0 on success, 1 when a tag or the working tree is wrong, 2 on a usage error.
    """
    if not argv or argv[0] not in ("build", "publish"):
        print(__doc__, file=sys.stderr)
        return 2
    publish = argv[0] == "publish"
    tags = git("tag", "--points-at", "HEAD").split()
    chosen, problems = releases(tags, packages(), only=argv[1:])
    if publish and git("status", "--porcelain"):
        problems.append("the working tree has changes: publish only a clean checkout of the tag")
    if problems:
        print("Nothing released:", *problems, sep="\n  ", file=sys.stderr)
        return 1
    shutil.rmtree(OUT, ignore_errors=True)
    for package in chosen:
        build(package, OUT / package.name)
    if publish:
        for package in chosen:
            upload(package, OUT / package.name)
    print("Released:" if publish else "Built in dist/release/:")
    for package in chosen:
        print(f"  {package.name} {package.version}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
