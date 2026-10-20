"""Shared setup: harnessd serving the help desk in ``tests/desk``, behind a test token."""

import sys
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from harnessweaver_sidecar.app import create_app
from harnessweaver_sidecar.main import load

DESK = Path(__file__).resolve().parent / "desk"
TOKEN = "sk-test-harnessd"

if str(DESK) not in sys.path:
    sys.path.insert(0, str(DESK))  # the spec names harnessd_desk:<thing>, as an app names its code


@pytest.fixture
def app() -> FastAPI:
    """A fresh harnessd for each test, so scripted replies and refunds start over."""
    import harnessd_desk.tools

    harnessd_desk.tools.REFUNDS.clear()
    return create_app(load(DESK / "harness.yaml"), token=TOKEN)


@pytest.fixture
def client(app: FastAPI) -> Iterator[TestClient]:
    """A client that sends the token with every request."""
    with TestClient(app, headers={"Authorization": f"Bearer {TOKEN}"}) as test_client:
        yield test_client
