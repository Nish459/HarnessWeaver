"""Runs the language-neutral fixtures in contracts/fixtures/conformance (RULES T4).

A test marked ``@pytest.mark.conformance_suite("<suite>")`` that takes a ``case``
argument runs once per case in that suite's JSON files.
"""

import json
from pathlib import Path
from typing import Any

import pytest


def _fixtures_root() -> Path:
    for parent in Path(__file__).resolve().parents:
        candidate = parent / "contracts" / "fixtures" / "conformance"
        if candidate.is_dir():
            return candidate
    raise RuntimeError("contracts/fixtures/conformance not found above this file")


FIXTURES_ROOT = _fixtures_root()


def load_suite(suite: str) -> list[dict[str, Any]]:
    cases: list[dict[str, Any]] = []
    for path in sorted((FIXTURES_ROOT / suite).glob("*.json")):
        document = json.loads(path.read_text(encoding="utf-8"))
        assert document["suite"] == suite, f"{path} declares suite {document['suite']!r}"
        cases.extend({**case, "_file": path.name} for case in document["cases"])
    assert cases, f"suite {suite!r} has no cases"
    return cases


def pytest_generate_tests(metafunc: pytest.Metafunc) -> None:
    marker = metafunc.definition.get_closest_marker("conformance_suite")
    if marker is None or "case" not in metafunc.fixturenames:
        return
    cases = load_suite(marker.args[0])
    ids = [f"{case['_file']}::{case['name']}" for case in cases]
    metafunc.parametrize("case", cases, ids=ids)


@pytest.fixture
def fixtures_root() -> Path:
    return FIXTURES_ROOT
