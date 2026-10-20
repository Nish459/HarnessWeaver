"""The ``harnessd`` command: a token, a spec, and 127.0.0.1 by default (S6)."""

from pathlib import Path
from typing import Any

import pytest
import uvicorn

from harnessweaver_sidecar import main as harnessd

DESK = Path(__file__).resolve().parent / "desk"


@pytest.fixture
def served(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """What uvicorn would have been asked to serve."""
    seen: dict[str, Any] = {}

    def run(app: Any, *, host: str, port: int) -> None:
        seen.update(app=app, host=host, port=port)

    monkeypatch.setattr(uvicorn, "run", run)
    return seen


def test_it_serves_the_spec_on_localhost_with_the_token(
    served: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("HARNESSD_TOKEN", "sk-test-harnessd")
    harnessd.main([str(DESK / "harness.yaml")])
    assert (served["host"], served["port"]) == ("127.0.0.1", 7070)
    assert served["app"].state.token == "sk-test-harnessd"
    assert served["app"].state.harness.name == "help-desk"


def test_it_refuses_to_start_without_a_token(
    served: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("OTHER_TOKEN", "")
    with pytest.raises(SystemExit, match="set OTHER_TOKEN"):
        harnessd.main([str(DESK / "harness.yaml"), "--token-env", "OTHER_TOKEN"])
    assert served == {}


def test_a_spec_that_doesnt_load_exits_with_its_error(
    served: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("HARNESSD_TOKEN", "sk-test-harnessd")
    (tmp_path / "harness.yaml").write_text("kind: Harness\n", encoding="utf-8")
    with pytest.raises(SystemExit) as exited:
        harnessd.main([str(tmp_path / "harness.yaml")])
    assert exited.value.code == 1
    assert capsys.readouterr().err.startswith("harnessd: ")
    assert served == {}
