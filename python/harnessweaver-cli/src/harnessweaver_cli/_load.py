"""Finding and loading specs for the CLI, including ``git:<ref>:<path>`` sources."""

import io
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path

import typer

from harnessweaver import Harness
from harnessweaver.core.errors import HarnessError, SpecError
from harnessweaver.core.ports import StateStore
from harnessweaver.spec import EffectiveSpec, load_spec

__all__ = ["fail", "load_effective", "load_harness", "spec_path"]

DEFAULT_SPEC = Path("harness.yaml")


def fail(error: HarnessError | str, code: int = 1) -> typer.Exit:
    """Print an error the way every command does and return the exit to raise.

    Commands that report checks (``eval run``, ``policy test``, ``replay``) exit 1
    when a check fails and 2 when they can't run, so CI can tell the two apart.
    """
    message = error.message if isinstance(error, HarnessError) else error
    typer.echo(f"error: {message}", err=True)
    return typer.Exit(code=code)


def spec_path(path: Path | None, code: int = 1) -> Path:
    """The spec to load. Its directory becomes importable, as when the app runs from
    there, so ``tasks.*.input`` and handler paths resolve."""
    found = path or DEFAULT_SPEC
    if not found.is_file():
        raise fail(f"no spec at {found}; pass the path to harness.yaml", code)
    directory = str(found.resolve().parent)
    if directory not in sys.path:
        sys.path.insert(0, directory)
    return found


def load_harness(
    path: Path | None,
    env: str | None,
    profile_dirs: list[Path],
    *,
    state: StateStore | None = None,
    code: int = 1,
) -> Harness:
    """Load and build the harness, the same way an app does (every check runs).
    ``state`` replaces the spec's state store (evals keep their runs in memory)."""
    try:
        effective = load_spec(spec_path(path, code), env=env, profile_dirs=profile_dirs)
        return Harness.from_spec(effective, state=state)
    except HarnessError as exc:
        raise fail(exc, code) from None


def _git(*args: str) -> bytes | None:
    """Run git and return its output, or ``None`` if it fails or isn't installed."""
    try:
        done = subprocess.run(["git", *args], capture_output=True, check=False)
    except OSError:
        return None
    return done.stdout if done.returncode == 0 else None


def _load_from_git(ref: str, raw_path: str, env: str | None, dirs: list[Path]) -> EffectiveSpec:
    """Load a spec as it stands at ``ref``, with the profiles that were committed with it.

    The whole tree at the ref is extracted, so ``.harness/profiles`` and file references come
    from the ref and not the working tree: otherwise a pull request that weakens only a
    profile would show no difference. A ``--profile-dir`` inside the repository is read from
    the ref too. One outside it, like ``HARNESSWEAVER_PROFILE_PATH``, isn't in git, so both
    sides of a diff see the same files.

    Raises:
        SpecError: If the ref or the path can't be read.
    """
    missing = SpecError(f"can't read {raw_path} at {ref} from git")
    # --end-of-options keeps a ref from being read as an option of git's.
    commit = _git("rev-parse", "--verify", "--quiet", "--end-of-options", f"{ref}^{{commit}}")
    top = _git("rev-parse", "--show-toplevel")
    if commit is None or top is None:
        raise missing
    root = Path(top.decode().strip()).resolve()
    archive = _git("-C", str(root), "archive", "--format=tar", commit.decode().strip())
    if archive is None:
        raise missing

    def inside(tree: Path, path: Path) -> Path | None:
        """Where ``path`` is in the extracted tree, if it's in the repository at all."""
        resolved = path.resolve()
        return tree / resolved.relative_to(root) if resolved.is_relative_to(root) else None

    with tempfile.TemporaryDirectory(prefix="harnessweaver-git-") as temporary:
        tree = Path(temporary).resolve()
        with tarfile.open(fileobj=io.BytesIO(archive)) as tar:
            tar.extractall(tree, filter="data")  # the data filter refuses paths out of the tree
        path = inside(tree, Path(raw_path))
        if path is None or not path.is_file():
            raise missing
        return load_spec(path, env=env, profile_dirs=[inside(tree, d) or d for d in dirs])


def load_effective(source: str, env: str | None, profile_dirs: list[Path]) -> EffectiveSpec:
    """Load a spec from a file, or from git as ``git:<ref>:<path>`` (for ``spec diff`` in CI)."""
    try:
        if not source.startswith("git:"):
            return load_spec(spec_path(Path(source)), env=env, profile_dirs=profile_dirs)
        ref, _, raw_path = source.removeprefix("git:").partition(":")
        if not ref or not raw_path:
            raise SpecError(f"{source!r} must look like git:<ref>:<path>")
        return _load_from_git(ref, raw_path, env, profile_dirs)
    except HarnessError as exc:
        raise fail(exc) from None
