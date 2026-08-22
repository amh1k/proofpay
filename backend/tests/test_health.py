from fastapi.testclient import TestClient

from proofpay.main import create_app


def test_health_reports_ok():
    client = TestClient(create_app())
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_health_reports_a_runnable_extractor():
    """The reported extractor must be one that can actually run."""
    client = TestClient(create_app())
    body = client.get("/health").json()

    assert body["receipt_extractor"] in {"qwen", "deterministic"}
