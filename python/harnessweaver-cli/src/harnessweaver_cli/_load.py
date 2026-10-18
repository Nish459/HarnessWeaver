"""Finding and loading specs for the CLI, including ``git:<ref>:<path>`` sources."""

import subprocess
import sys
from pathlib import Path
from typing import Any

import typer

from harnessweaver import Harness
from harnessweaver.core.errors import HarnessError, SpecError
from harnessweaver.core.registry import PluginCatalog
from harnessweaver.spec import EffectiveSpec, load_spec, spec_from_documents
from harnessweaver.spec.sources import BuiltinProfiles, PluginProfiles, ProfileDirectories
from harnessweaver.spec.yaml import load_yaml

__all__ = ["fail", "load_effective", "load_harness", "spec_path"]

DEFAULT_SPEC = Path("harness.yaml")


def fail(error: HarnessError | str) -> typer.Exit:
    """Print an error the way every command does and return the exit to raise."""
    message = error.message if isinstance(error, HarnessError) else error
    typer.echo(f"error: {message}", err=True)
    return typer.Exit(code=1)


def spec_path(path: Path | None) -> Path:
    """The spec to load. Its directory becomes importable, as when the app runs from
    there, so ``tasks.*.input`` and handler paths resolve."""
    found = path or DEFAULT_SPEC
    if not found.is_file():
        raise fail(f"no spec at {found}; pass the path to harness.yaml")
    directory = str(found.resolve().parent)
    if directory not in sys.path:
        sys.path.insert(0, directory)
    return found


def load_harness(path: Path | None, env: str | None, profile_dirs: list[Path]) -> Harness:
    """Load and build the harness, the same way an app does (every check runs)."""
    try:
        return Harness.load(spec_path(path), env=env, profile_dirs=profile_dirs)
    except HarnessError as exc:
        raise fail(exc) from None


def _git_show(ref: str, path: str) -> str | None:
    target = path if Path(path).is_absolute() else f"./{path}"
    done = subprocess.run(
        ["git", "show", f"{ref}:{target}"], capture_output=True, text=True, check=False
    )
    return done.stdout if done.returncode == 0 else None


def load_effective(source: str, env: str | None, profile_dirs: list[Path]) -> EffectiveSpec:
    """Load a spec from a file, or from git as ``git:<ref>:<path>`` (for ``spec diff`` in CI).

    A spec read from git resolves its profiles from the working tree, like a
    file next to the current one would.
    """
    try:
        if not source.startswith("git:"):
            return load_spec(spec_path(Path(source)), env=env, profile_dirs=profile_dirs)
        ref, _, raw_path = source.removeprefix("git:").partition(":")
        if not ref or not raw_path:
            raise SpecError(f"{source!r} must look like git:<ref>:<path>")
        text = _git_show(ref, raw_path)
        if text is None:
            raise SpecError(f"can't read {raw_path} at {ref} from git")
        path = Path(raw_path)
        document: Any = load_yaml(text, source)
        overlay: Any = None
        if env:
            overlay_text = _git_show(ref, str(path.with_name(f"{path.stem}.{env}{path.suffix}")))
            overlay = load_yaml(overlay_text, f"{source} ({env})") if overlay_text else None
        if not isinstance(document, dict):
            raise SpecError(f"{source} must be a YAML map")
        resolvers = [
            BuiltinProfiles(),
            PluginProfiles(PluginCatalog.default()),
            ProfileDirectories.from_environment(path.parent, profile_dirs),
        ]
        return spec_from_documents(
            document,  # pyright: ignore[reportUnknownArgumentType]
            resolvers=resolvers,
            overlay=overlay if isinstance(overlay, dict) else None,  # pyright: ignore[reportUnknownArgumentType]
            app_name=path.name,
            app_source=source,
            directory=path.parent,
        )
    except HarnessError as exc:
        raise fail(exc) from None
