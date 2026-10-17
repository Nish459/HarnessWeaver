from fastapi.testclient import TestClient

import harnessweaver
import harnessweaver_sidecar
from harnessweaver_sidecar.app import create_app


def test_health_reports_versions() -> None:
    client = TestClient(create_app())
    response = client.get("/v1/health")
    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "harnessd": harnessweaver_sidecar.__version__,
        "harnessweaver": harnessweaver.__version__,
    }
