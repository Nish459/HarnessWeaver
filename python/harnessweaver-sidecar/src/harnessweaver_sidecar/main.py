"""The ``harnessd`` command: load one spec and serve it (RULES S6)."""

import argparse
import os
import sys
from pathlib import Path

import uvicorn

from harnessweaver import Harness, load_spec
from harnessweaver.core.errors import HarnessError
from harnessweaver_sidecar.app import DEFAULT_MAX_BODY_BYTES, create_app

__all__ = ["load", "main", "serve"]

DEFAULT_PORT = 7070
TOKEN_ENV = "HARNESSD_TOKEN"


def load(spec: Path, env: str | None = None, profile_dirs: list[Path] | None = None) -> Harness:
    """Build the harness to serve, as an app would. The spec's directory becomes
    importable, so handler and tool paths next to it resolve (like the CLI).

    Raises:
        HarnessError: For a spec that doesn't load.
    """
    directory = str(spec.resolve().parent)
    if directory not in sys.path:
        sys.path.insert(0, directory)
    return Harness.from_spec(load_spec(spec, env=env, profile_dirs=profile_dirs or []))


def serve(
    spec: Path,
    *,
    env: str | None = None,
    profile_dirs: list[Path] | None = None,
    host: str = "127.0.0.1",
    port: int = DEFAULT_PORT,
    token_env: str = TOKEN_ENV,
    max_body_bytes: int = DEFAULT_MAX_BODY_BYTES,
) -> None:
    """Serve ``spec`` until stopped. It binds to 127.0.0.1 unless told otherwise.

    Raises:
        SystemExit: When the token variable is empty: harnessd never runs open (S6).
        HarnessError: For a spec that doesn't load.
    """
    token = os.environ.get(token_env, "")
    if not token:
        raise SystemExit(f"harnessd: set {token_env} to the bearer token clients must send (S6)")
    app = create_app(load(spec, env, profile_dirs), token=token, max_body_bytes=max_body_bytes)
    uvicorn.run(app, host=host, port=port)


def main(argv: list[str] | None = None) -> None:
    """Run harnessd from the command line."""
    parser = argparse.ArgumentParser(prog="harnessd", description="The HarnessWeaver sidecar")
    parser.add_argument("spec", nargs="?", type=Path, default=Path("harness.yaml"))
    parser.add_argument("-e", "--env", help="the overlay; defaults to $HARNESSWEAVER_ENV")
    parser.add_argument("--profile-dir", type=Path, action="append", default=[])
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--token-env", default=TOKEN_ENV, help="where the bearer token is")
    parser.add_argument(
        "--max-body-bytes",
        type=int,
        default=DEFAULT_MAX_BODY_BYTES,
        help="the largest request body read; anything over answers 413",
    )
    args = parser.parse_args(argv)
    try:
        serve(
            args.spec,
            env=args.env,
            profile_dirs=args.profile_dir,
            host=args.host,
            port=args.port,
            token_env=args.token_env,
            max_body_bytes=args.max_body_bytes,
        )
    except HarnessError as exc:
        parser.exit(1, f"harnessd: {exc.message}\n")
