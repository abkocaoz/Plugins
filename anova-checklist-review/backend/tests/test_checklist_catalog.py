from app.services.checklist_catalog import CATALOG_DIR, load_catalog_file


def test_software_code_standard_scaffold_does_not_invent_template_files():
    data = load_catalog_file()
    assert data["key"] == "software_code_standard"
    gap = data["template_gap"]
    assert gap["claimed_template_file_count"] == 0
    assert gap["status"] == "synthetic_fixture_only"
    assert "do not claim" in gap["note"].lower()
    # Synthetic fixture only — not a production template count claim
    fixture = CATALOG_DIR / "fixtures" / "software_code_standard_synthetic_v1.xlsx"
    assert fixture.is_file()
    assert data["excel_template_path"] == "fixtures/software_code_standard_synthetic_v1.xlsx"
    assert len(data["items"]) >= 6
    methods = {i["method"] for i in data["items"]}
    assert "deterministic_rule" in methods
    assert "document_content" in methods
    assert "manual_review" in methods
    for item in data["items"]:
        assert item["prompt"]
        cells = item["excel_cells"]
        assert cells["answer"]
        assert cells["chapter"]
        assert cells["comment"]
        assert cells["references"]
        assert cells["reviewed_item"]
        assert cells["status"]
        assert "subchecks" in item
        assert "acceptance_criteria" in item
        assert "method" in item
