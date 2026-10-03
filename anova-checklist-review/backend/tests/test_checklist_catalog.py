from app.services.checklist_catalog import load_catalog_file


def test_software_code_standard_scaffold_does_not_invent_template_files():
    data = load_catalog_file()
    assert data["key"] == "software_code_standard"
    assert data["excel_template_path"] is None
    gap = data["template_gap"]
    assert gap["status"] == "missing_in_repo"
    assert gap["claimed_template_file_count"] == 0
    assert len(data["items"]) >= 6
    methods = {i["method"] for i in data["items"]}
    assert "deterministic_rule" in methods
    assert "document_content" in methods
    assert "manual_review" in methods
    # each item has required Phase 4 fields
    for item in data["items"]:
        assert item["prompt"]
        assert item["excel_cells"]["answer"]
        assert "subchecks" in item
        assert "acceptance_criteria" in item
        assert "method" in item
