"""The sidecar's checked-in contracts stay in step with the code (R11, ADR-0038)."""

import re
from pathlib import Path

from harnessweaver_sidecar.app import openapi_document
from harnessweaver_sidecar.openapi import FILE_NAME, main, render

ROOT = Path(__file__).resolve().parents[3]
CONTRACTS = ROOT / "contracts"
PROTO = CONTRACTS / "proto" / "harnessweaver" / "v1" / "harnessd.proto"


def openapi_routes() -> set[tuple[str, str]]:
    return {
        (method, path)
        for path, operations in openapi_document()["paths"].items()
        for method in operations
    }


def test_the_checked_in_openapi_document_has_no_drift() -> None:
    checked_in = (CONTRACTS / "openapi" / FILE_NAME).read_text(encoding="utf-8")
    assert checked_in == render(), "run make schemas"


def test_the_proto_mirrors_every_route() -> None:
    text = PROTO.read_text(encoding="utf-8")
    proto_routes = set(re.findall(r'\b(get|post): "([^"]+)"', text))
    assert proto_routes == openapi_routes()


def test_the_exporter_writes_and_checks(tmp_path: Path) -> None:
    assert main([str(tmp_path), "--check"]) == 1
    assert main([str(tmp_path)]) == 0
    assert main([str(tmp_path), "--check"]) == 0
