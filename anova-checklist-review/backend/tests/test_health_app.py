from fastapi.testclient import TestClient

from app.main import app


def test_health_endpoint():
    client = TestClient(app)
    r = client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["phase"] == 1


def test_meta_lists_reference_statuses():
    client = TestClient(app)
    r = client.get("/api/v1/meta")
    assert r.status_code == 200
    statuses = r.json()["reference_statuses"]
    assert "VERIFIED" in statuses
    assert "INSUFFICIENT_EVIDENCE" in statuses
    assert "MISSING_SOURCE" in statuses
