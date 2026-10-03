"""Load / seed versioned checklist catalogs from the Phase 7 registry."""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.entities import ChecklistDefinition, ChecklistItem

CATALOG_DIR = Path(__file__).resolve().parents[1] / "catalogs"
REGISTRY_PATH = CATALOG_DIR / "checklist_registry.json"
SOFTWARE_CODE_STANDARD_PATH = CATALOG_DIR / "software_code_standard_v1.json"


def load_registry() -> dict[str, Any]:
    data = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
    if not isinstance(data.get("entries"), list):
        raise ValueError(f"Invalid checklist registry: {REGISTRY_PATH}")
    return data


def registry_entries() -> list[dict[str, Any]]:
    return list(load_registry().get("entries") or [])


def registry_honesty() -> dict[str, Any]:
    return dict(load_registry().get("honesty") or {})


def seedable_catalog_paths() -> dict[str, Path]:
    """definition_key → catalog JSON path for seedable registry entries."""
    out: dict[str, Path] = {}
    for entry in registry_entries():
        if not entry.get("seedable"):
            continue
        key = entry.get("definition_key")
        fname = entry.get("catalog_file")
        if not key or not fname:
            continue
        path = CATALOG_DIR / fname
        if path.is_file():
            out[key] = path
    return out


# Back-compat alias used across the codebase
CATALOG_PATHS: dict[str, Path] = seedable_catalog_paths()


def refresh_catalog_paths() -> dict[str, Path]:
    global CATALOG_PATHS
    CATALOG_PATHS = seedable_catalog_paths()
    return CATALOG_PATHS


def get_registry_entry(key: str) -> dict[str, Any] | None:
    for entry in registry_entries():
        if entry.get("definition_key") == key:
            return entry
    return None


def list_catalog_keys() -> list[str]:
    return sorted(seedable_catalog_paths().keys())


def list_registry_keys(*, seedable_only: bool = False) -> list[str]:
    keys = []
    for e in registry_entries():
        if seedable_only and not e.get("seedable"):
            continue
        if e.get("definition_key"):
            keys.append(e["definition_key"])
    return keys


def load_catalog_file(path: Path | None = None, *, key: str | None = None) -> dict[str, Any]:
    paths = seedable_catalog_paths()
    if path is None and key:
        path = paths.get(key)
        if path is None:
            raise KeyError(f"Unknown or non-seedable catalog key: {key}")
    p = path or paths.get("software_code_standard") or SOFTWARE_CODE_STANDARD_PATH
    data = json.loads(p.read_text(encoding="utf-8"))
    if not data.get("key"):
        raise ValueError(f"Invalid catalog file (missing key): {p}")
    if "items" not in data or not isinstance(data["items"], list):
        raise ValueError(f"Invalid catalog file (items must be a list): {p}")
    if not data["items"]:
        raise ValueError(f"Invalid catalog file (empty items — use awaiting_template slot instead): {p}")
    return data


def validate_catalog_dict(data: dict[str, Any]) -> list[str]:
    """Return list of validation errors (empty = OK). Used for onboarding checks."""
    errors: list[str] = []
    if not data.get("key"):
        errors.append("missing key")
    if not data.get("title"):
        errors.append("missing title")
    if not data.get("version_label"):
        errors.append("missing version_label")
    items = data.get("items")
    if not isinstance(items, list) or not items:
        errors.append("items must be a non-empty list")
        return errors
    mapping = data.get("cell_mapping") or {}
    cols = mapping.get("columns") or {}
    if "answer" not in cols:
        errors.append("cell_mapping.columns.answer required")
    invent = set(mapping.get("do_not_invent_columns") or [])
    for bad in ("Author's Answer", "Resolved SVN Revision"):
        if bad not in invent and bad in cols.values():
            errors.append(f"invented/forbidden column present: {bad}")
    for i, item in enumerate(items):
        prefix = f"items[{i}]"
        if not item.get("item_key"):
            errors.append(f"{prefix}.item_key required")
        if not item.get("prompt"):
            errors.append(f"{prefix}.prompt required")
        if not item.get("method"):
            errors.append(f"{prefix}.method required")
        cells = item.get("excel_cells") or {}
        if not cells.get("answer"):
            errors.append(f"{prefix}.excel_cells.answer required")
        if "is_applicable" in cells and cells.get("is_applicable") == cells.get("answer"):
            errors.append(f"{prefix}: is_applicable must differ from answer (conformity)")
    gap = data.get("template_gap") or {}
    if gap.get("claimed_template_file_count", 0) not in (0, None):
        # Only allow 0 in scaffolds unless a real file path is also declared
        if not data.get("excel_template_path"):
            errors.append("claimed_template_file_count must be 0 when excel_template_path is null")
    return errors


def validate_onboarding_package(
    *,
    definition_key: str,
    catalog: dict[str, Any],
    template_path: Path | None = None,
) -> dict[str, Any]:
    """Validate a candidate catalog (+ optional template file) for registry onboarding."""
    errors = validate_catalog_dict(catalog)
    if catalog.get("key") and catalog["key"] != definition_key:
        errors.append(f"catalog.key {catalog['key']!r} != definition_key {definition_key!r}")
    template_ok = None
    if template_path is not None:
        template_ok = template_path.is_file()
        if not template_ok:
            errors.append(f"template file missing: {template_path}")
        elif template_path.suffix.lower() not in {".xlsx", ".xlsm"}:
            errors.append("template must be .xlsx or .xlsm")
    entry = get_registry_entry(definition_key)
    return {
        "definition_key": definition_key,
        "ok": not errors,
        "errors": errors,
        "registry_entry": entry,
        "template_present": template_ok,
        "honesty": registry_honesty(),
    }


def registry_public_view() -> dict[str, Any]:
    """API-facing registry snapshot (no invented production template counts)."""
    reg = load_registry()
    honesty = dict(reg.get("honesty") or {})
    entries = []
    for e in reg.get("entries") or []:
        key = e.get("definition_key")
        catalog_file = e.get("catalog_file")
        path = CATALOG_DIR / catalog_file if catalog_file else None
        fixture = e.get("synthetic_fixture")
        fixture_path = CATALOG_DIR / fixture if fixture else None
        entries.append(
            {
                "definition_key": key,
                "title": e.get("title"),
                "status": e.get("status"),
                "seedable": bool(e.get("seedable")),
                "catalog_file": catalog_file,
                "catalog_present": bool(path and path.is_file()),
                "synthetic_fixture": fixture,
                "synthetic_fixture_present": bool(fixture_path and fixture_path.is_file()),
                "methods_focus": e.get("methods_focus") or [],
                "notes": e.get("notes"),
            }
        )
    return {
        "registry_version": reg.get("registry_version"),
        "honesty": honesty,
        "seedable_keys": list_catalog_keys(),
        "all_keys": list_registry_keys(),
        "entries": entries,
        "counts": {
            "total_registered": len(entries),
            "seedable": sum(1 for e in entries if e["seedable"]),
            "awaiting_template": sum(1 for e in entries if e["status"] == "awaiting_template"),
            "scaffold_implemented": sum(
                1 for e in entries if e["status"] == "scaffold_implemented"
            ),
            "representative_scaffold": sum(
                1 for e in entries if e["status"] == "representative_scaffold"
            ),
            "claimed_production_template_count": honesty.get(
                "claimed_production_template_count", 0
            ),
        },
    }


async def seed_catalog(
    session: AsyncSession, data: dict[str, Any] | None = None, *, replace_items: bool = True
) -> ChecklistDefinition:
    data = data or load_catalog_file()
    errs = validate_catalog_dict(data)
    if errs:
        raise ValueError(f"catalog validation failed: {errs}")
    existing = await session.scalar(
        select(ChecklistDefinition).where(ChecklistDefinition.key == data["key"])
    )
    entry = get_registry_entry(data["key"])
    meta_base = {
        "template_gap": data.get("template_gap"),
        "cell_mapping": data.get("cell_mapping"),
        "catalog_source": "scaffold_json",
        "registry_status": (entry or {}).get("status"),
    }
    if existing is None:
        definition = ChecklistDefinition(
            id=uuid.uuid4(),
            key=data["key"],
            title=data["title"],
            description=data.get("description"),
            version_label=data.get("version_label") or "1.0",
            excel_template_path=data.get("excel_template_path"),
            meta=meta_base,
        )
        session.add(definition)
        await session.flush()
    else:
        definition = existing
        definition.title = data["title"]
        definition.description = data.get("description")
        definition.version_label = data.get("version_label") or definition.version_label
        definition.excel_template_path = data.get("excel_template_path")
        definition.meta = {**(definition.meta or {}), **meta_base}
        if replace_items:
            old = (
                await session.scalars(
                    select(ChecklistItem).where(ChecklistItem.definition_id == definition.id)
                )
            ).all()
            for row in old:
                await session.delete(row)
            await session.flush()

    existing_items = {
        i.item_key: i
        for i in (
            await session.scalars(
                select(ChecklistItem).where(ChecklistItem.definition_id == definition.id)
            )
        ).all()
    }
    for idx, raw in enumerate(data["items"]):
        schema = {
            "question_number": raw.get("question_number"),
            "file": raw.get("file"),
            "sheet": raw.get("sheet"),
            "row": raw.get("row"),
            "excel_cells": raw.get("excel_cells") or {},
            "applicability": raw.get("applicability"),
            "required_docs": raw.get("required_docs") or [],
            "related_standard_clauses": raw.get("related_standard_clauses") or [],
            "reference_dependencies": raw.get("reference_dependencies") or [],
            "subchecks": raw.get("subchecks") or [],
            "acceptance_criteria": raw.get("acceptance_criteria"),
            "requires_full_scan": bool(raw.get("requires_full_scan")),
            "method_config": raw.get("method_config") or {},
        }
        answer_cell = (raw.get("excel_cells") or {}).get("answer") or raw.get("excel_cell")
        item = existing_items.get(raw["item_key"])
        if item is None:
            item = ChecklistItem(
                id=uuid.uuid4(),
                definition_id=definition.id,
                item_key=raw["item_key"],
                prompt=raw["prompt"],
                method=raw.get("method") or "manual_review",
                depends_on_references=bool(raw.get("depends_on_references")),
                excel_cell=answer_cell,
                sort_order=idx,
                schema_json=schema,
            )
            session.add(item)
        else:
            item.prompt = raw["prompt"]
            item.method = raw.get("method") or item.method
            item.depends_on_references = bool(raw.get("depends_on_references"))
            item.excel_cell = answer_cell
            item.sort_order = idx
            item.schema_json = schema
    await session.flush()
    return definition


async def seed_catalog_by_key(
    session: AsyncSession, key: str, *, replace_items: bool = True
) -> ChecklistDefinition:
    paths = seedable_catalog_paths()
    if key not in paths:
        entry = get_registry_entry(key)
        if entry and entry.get("status") == "awaiting_template":
            raise KeyError(
                f"Catalog {key!r} is registered but awaiting_template "
                f"(not seedable). Supply catalog JSON + template per docs/checklist-onboarding.md"
            )
        raise KeyError(f"Unknown catalog key: {key}. Seedable: {sorted(paths)}")
    return await seed_catalog(
        session, load_catalog_file(key=key), replace_items=replace_items
    )


async def ensure_catalog_seeded(
    session: AsyncSession, key: str
) -> ChecklistDefinition:
    existing = await session.scalar(
        select(ChecklistDefinition).where(ChecklistDefinition.key == key)
    )
    if existing is not None:
        return existing
    return await seed_catalog_by_key(session, key)


async def seed_all_seedable(
    session: AsyncSession, *, replace_items: bool = True
) -> list[str]:
    seeded: list[str] = []
    for key in list_catalog_keys():
        await seed_catalog_by_key(session, key, replace_items=replace_items)
        seeded.append(key)
    return seeded
