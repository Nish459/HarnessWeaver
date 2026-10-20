"""``harnessweaver sidecar``: run harnessd for a spec, if harnessweaver-sidecar is installed.

The CLI doesn't depend on the sidecar package (it brings FastAPI and uvicorn), so
the import happens only when the command runs.
"""

import importlib
from typing import Annotated

import typer

from harnessweaver.core.errors import HarnessError
from harnessweaver_cli._load import fail, spec_path
from harnessweaver_cli.spec import Env, Path_, ProfileDirs

__all__ = ["sidecar"]


def sidecar(
    path: Path_ = None,
    env: Env = None,
    profile_dir: ProfileDirs = None,
    host: Annotated[str, typer.Option(help="Where to listen; keep 127.0.0.1 (S6).")] = "127.0.0.1",
    port: Annotated[int, typer.Option(help="The port.")] = 7070,
    token_env: Annotated[
        str, typer.Option(help="The variable holding the bearer token clients send.")
    ] = "HARNESSD_TOKEN",
) -> None:
    """Serve the spec to other languages over HTTP: run harnessd (DESIGNS No. 24)."""
    try:
        harnessd = importlib.import_module("harnessweaver_sidecar.main")
    except ImportError:
        raise fail("harnessd isn't installed; run: uv add harnessweaver-sidecar") from None
    try:
        harnessd.serve(
            spec_path(path),
            env=env,
            profile_dirs=profile_dir or [],
            host=host,
            port=port,
            token_env=token_env,
        )
    except HarnessError as exc:
        raise fail(exc) from None
