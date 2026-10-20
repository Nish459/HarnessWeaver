"""The sidecar's OpenAPI document, checked in under ``contracts/openapi`` (R11, ADR-0038).

The document is generated from the routes and the wire models, like the JSON
Schemas are from the contract models (ADR-0005), and a test fails when the
checked-in copy drifts. ``make schemas`` writes it; ``make schemas-check``
reports drift.
"""

import argparse
import json
from pathlib import Path

from harnessweaver_sidecar.app import openapi_document

__all__ = ["main", "render"]

FILE_NAME = "harnessd.openapi.json"


def render() -> str:
    """The document exactly as it is checked in."""
    return json.dumps(openapi_document(), indent=2, ensure_ascii=True) + "\n"


def main(argv: list[str] | None = None) -> int:
    """Write the document into a directory, or with ``--check`` report drift (exit 1)."""
    parser = argparse.ArgumentParser(prog="harnessd-openapi")
    parser.add_argument("directory", type=Path, help="usually contracts/openapi")
    parser.add_argument("--check", action="store_true", help="report drift instead of writing")
    args = parser.parse_args(argv)
    path: Path = args.directory / FILE_NAME
    if args.check:
        if not path.is_file() or path.read_text(encoding="utf-8") != render():
            print(f"{path} is out of date; run make schemas")  # noqa: T201 - command-line output
            return 1
        return 0
    args.directory.mkdir(parents=True, exist_ok=True)
    path.write_text(render(), encoding="utf-8")
    print(f"wrote {path}")  # noqa: T201 - command-line output
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
