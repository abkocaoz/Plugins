"""Load / seed versioned checklist catalogs into checklist_definitions + items."""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.entities import ChecklistDefinition, ChecklistItem

CATALOG_DIR = Path(__file__).resolve().parents[1] / "catalogs"
SOFTWARE_CODE_STANDARD_PATH = CATALOG_DIR / "software_code_standard_v1.json"


def load_catalog_file(path: Path | None = None) -> dict[str, Any]:
    p = path or SOFTWARE_CODE_STANDARD_PATH
    data = json.loads(p.read_text(encoding="utf-8"))
    if not data.get("key") or not data.get("items"):
        raise ValueError(f"Invalid catalog file: {p}")
    return data


async def seed_catalog(
    session: AsyncSession, data: dict[str, Any] | None = None, *, replace_items: bool = True
) -> ChecklistDefinition:
    data = data or load_catalog_file()
    existing = await session.scalar(
        select(ChecklistDefinition).where(ChecklistDefinition.key == data["key"])
    )
    if existing is None:
        definition = ChecklistDefinition(
            id=uuid.uuid4(),
            key=data["key"],
            title=data["title"],
            description=data.get("description"),
            version_label=data.get("version_label") or "1.0",
            excel_template_path=data.get("excel_template_path"),
            meta={
                "template_gap": data.get("template_gap"),
                "cell_mapping": data.get("cell_mapping"),
                "catalog_source": "scaffold_json",
            },
        )
        session.add(definition)
        await session.flush()
    else:
        definition = existing
        definition.title = data["title"]
        definition.description = data.get("description")
        definition.version_label = data.get("version_label") or definition.version_label
        definition.excel_template_path = data.get("excel_template_path")
        definition.meta = {
            **(definition.meta or {}),
            "template_gap": data.get("template_gap"),
            "cell_mapping": data.get("cell_mapping"),
            "catalog_source": "scaffold_json",
        }
        if replace_items:
            old = (
                await session.scalars(
                    select(ChecklistItem).where(ChecklistItem.definition_id == definition.id)
                )
            ).all()
            for row in old:
                await session.delete(row)
            await session.flush()

    # Upsert items
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
