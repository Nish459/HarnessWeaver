"""Entry point for the ``harnessd`` command."""

import argparse

import uvicorn

from harnessweaver_sidecar.app import create_app


def main(argv: list[str] | None = None) -> None:
    """Run harnessd. It binds to 127.0.0.1 unless told otherwise (RULES S6)."""
    parser = argparse.ArgumentParser(prog="harnessd", description="HarnessWeaver sidecar")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=7070)
    args = parser.parse_args(argv)
    uvicorn.run(create_app(), host=args.host, port=args.port)
