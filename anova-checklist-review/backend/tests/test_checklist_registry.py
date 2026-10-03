"""Phase 7: checklist registry + onboarding validation path."""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app
from app.services.checklist_catalog import (
    CATALOG_DIR,
    get_registry_entry,
    list_catalog_keys,
    list_registry_keys,
    load_catalog_file,
    load_registry,
    registry_honesty,
    registry_public_view,
    seedable_catalog_paths,
    validate_catalog_dict,
    validate_onboarding_package,
)


def test_registry_honesty_does_not_claim_21_templates():
    honesty = registry_honesty()
    assert honesty.get("claimed_production_template_count") == 0
    note = (honesty.get("note") or "").lower()
    assert "do not claim" in note or "21" in note
    view = registry_public_view()
    assert view["counts"]["claimed_production_template_count"] == 0
    assert view["counts"]["awaiting_template"] >= 1
    assert view["counts"]["scaffold_implemented"] >= 3
    assert view["counts"]["representative_scaffold"] >= 2
    # Must not equal a fabricated "21 full checklists" claim
    assert view["counts"]["seedable"] < 21
    assert view["counts"]["total_registered"] < 21 or view["counts"]["seedable"] < view["counts"]["total_registered"]


def test_seedable_paths_match_catalog_files():
    paths = seedable_catalog_paths()
    assert "software_code_standard" in paths
    assert "data_icd" in paths
    assert "seci" in paths
    assert "requirements_traceability" in paths
    assert "configuration_management" in paths
    assert "design_review" not in paths  # awaiting_template
    for key, path in paths.items():
        assert path.is_file(), key
        data = load_catalog_file(key=key)
        assert data["key"] == key
        assert validate_catalog_dict(data) == []


def test_awaiting_template_slots_are_registered_not_seedable():
    entry = get_registry_entry("design_review")
    assert entry is not None
    assert entry["status"] == "awaiting_template"
    assert entry.get("seedable") is False
    assert entry.get("catalog_file") is None
    all_keys = list_registry_keys()
    seedable = list_catalog_keys()
    assert "design_review" in all_keys
    assert "design_review" not in seedable


def test_validate_onboarding_package_ok_and_reject():
    data = load_catalog_file(key="configuration_management")
    result = validate_onboarding_package(
        definition_key="configuration_management",
        catalog=data,
        template_path=None,
    )
    assert result["ok"] is True
    assert result["errors"] == []

    bad = dict(data)
    bad["key"] = "wrong_key"
    bad["items"] = [{"item_key": "X", "prompt": "", "method": "manual_review", "excel_cells": {}}]
    result_bad = validate_onboarding_package(
        definition_key="configuration_management",
        catalog=bad,
    )
    assert result_bad["ok"] is False
    assert result_bad["errors"]


def test_registry_api_endpoint():
    client = TestClient(app)
    r = client.get("/api/v1/checklists/registry")
    assert r.status_code == 200
    body = r.json()
    assert body["counts"]["claimed_production_template_count"] == 0
    keys = {e["definition_key"] for e in body["entries"]}
    assert "software_code_standard" in keys
    assert "requirements_traceability" in keys
    assert "design_review" in keys


def test_validate_onboarding_api():
    client = TestClient(app)
    catalog = load_catalog_file(key="requirements_traceability")
    r = client.post(
        "/api/v1/checklists/registry/validate-onboarding",
        json={"definition_key": "requirements_traceability", "catalog": catalog},
    )
    assert r.status_code == 200
    assert r.json()["ok"] is True


def test_registry_file_lists_entries_without_inventing_full_packs():
    reg = load_registry()
    awaiting = [e for e in reg["entries"] if e["status"] == "awaiting_template"]
    assert len(awaiting) >= 4
    for e in awaiting:
        assert not e.get("catalog_file")
        # No phantom fixture files for empty slots
        if e.get("synthetic_fixture"):
            assert (CATALOG_DIR / e["synthetic_fixture"]).is_file()


def test_representative_scaffolds_are_thin():
    for key in ("requirements_traceability", "configuration_management"):
        data = load_catalog_file(key=key)
        assert 1 <= len(data["items"]) <= 6
        assert data["excel_template_path"] is None
        assert data["template_gap"]["claimed_template_file_count"] == 0
