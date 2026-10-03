from fastapi.testclient import TestClient

from app.main import app


def test_health_endpoint():
    client = TestClient(app)
    r = client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["phase"] == 4


def test_meta_lists_reference_statuses():
    client = TestClient(app)
    r = client.get("/api/v1/meta")
    assert r.status_code == 200
    statuses = r.json()["reference_statuses"]
    assert "VERIFIED" in statuses
    assert "INSUFFICIENT_EVIDENCE" in statuses
    assert "MISSING_SOURCE" in statuses


def test_ui_hooks():
    client = TestClient(app)
    ui = client.get("/ui")
    assert ui.status_code == 200
    assert "Start Live Demo" in ui.text
    assert "Live Demo" in ui.text
    assert "Reference review" in client.get("/ui/references").text
    assert "Software Code Standard" in client.get("/ui/checklist").text


def test_catalog_meta_endpoint():
    client = TestClient(app)
    r = client.get("/api/v1/checklists/catalog/software-code-standard/meta")
    assert r.status_code == 200
    body = r.json()
    assert body["template_gap"]["claimed_template_file_count"] == 0
    assert body["template_gap"]["status"] == "synthetic_fixture_only"
    assert body["excel_template_path"] == "fixtures/software_code_standard_synthetic_v1.xlsx"
