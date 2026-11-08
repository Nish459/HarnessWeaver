"""The web app recipe: the tutorial's support desk served over HTTP, offline."""

import shutil
from collections.abc import Callable
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

SetUp = Callable[[str], Any]
APP = Path(__file__).resolve().parents[1] / "web_app" / "app.py"

ANN = {"Authorization": "Bearer token-ann"}
FIONA = {"Authorization": "Bearer token-fiona"}
CHARGED_TWICE = {"text": "I was charged twice for my Pro plan. - ann@example.com"}


def test_the_desk_serves_runs_and_approvals(chapter: SetUp) -> None:
    desk = chapter("evals")  # the project as it stands at the end of the tutorial
    shutil.copy(APP, desk.folder / "app.py")
    with TestClient(desk.script("app.py").app) as client:
        triaged = client.post("/triage", json=CHARGED_TWICE, headers=ANN)
        assert triaged.status_code == 200
        body = triaged.json()
        assert body["status"] == "completed"
        assert body["output"]["category"] == "billing"
        assert "trace" not in body

        # A retry with the same key gets the first run back, but only for the same caller.
        retry = {**ANN, "Idempotency-Key": "ticket-17"}
        first = client.post("/triage", json=CHARGED_TWICE, headers=retry).json()
        assert client.post("/triage", json=CHARGED_TWICE, headers=retry).json() == first
        fiona_retry = {**FIONA, "Idempotency-Key": "ticket-17"}
        other = client.post("/triage", json=CHARGED_TWICE, headers=fiona_retry).json()
        assert other["run_id"] != first["run_id"]

        # A refund over $100 waits for finance: 202, then an approval from the right person.
        waiting = client.post("/orders", json={"text": "Refund $250 on order A-1001."}, headers=ANN)
        assert waiting.status_code == 202
        pending = waiting.json()
        assert pending["status"] == "awaiting_approval"
        url = f"/runs/{pending['run_id']}/approvals/{pending['approval']['approval_id']}"
        assert client.post(url, json={"decision": "approve"}, headers=ANN).status_code == 403
        done = client.post(url, json={"decision": "approve"}, headers=FIONA)
        assert done.status_code == 200
        assert done.json()["output"] == "Done: the refund is on its way to your card."
        assert client.post(url, json={"decision": "approve"}, headers=FIONA).status_code == 404

        # Policy blocks a refund over $500 before the tool runs.
        refused = client.post("/orders", json={"text": "Refund $900 on order A-1001."}, headers=ANN)
        assert refused.status_code == 422
        assert refused.json()["error"]["details"]["code"] == "policy_denied"

        nobody = client.post("/triage", json=CHARGED_TWICE, headers={"Authorization": "Bearer x"})
        assert nobody.status_code == 401
