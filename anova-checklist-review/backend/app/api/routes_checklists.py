"""Checklist catalog + evaluation + human review + Excel export APIs (Phases 4–5)."""

from __future__ import annotations

import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_dev_token
from app.core.config import get_settings
from app.core.job_types import JobType
from app.db.session import get_db
from app.models.entities import (
    ChecklistAnswer,
    ChecklistDefinition,
    ChecklistItem,
    ChecklistRun,
    Document,
    DocumentVersion,
    EvidenceLink,
    Export,
    Project,
    ReviewerDecision,
)
from app.schemas.common import JobOut, ORMModel
from app.services.checklist_catalog import load_catalog_file, seed_catalog
from app.services.excel_export import resolve_template_path
from app.services.human_review import (
    list_decisions_for_answer,
    record_human_decision,
    related_reference_findings_for_answer,
)
from app.services.jobs import enqueue_job, make_idempotency_key

router = APIRouter(prefix="/api/v1", tags=["checklists"], dependencies=[Depends(require_dev_token)])


class ChecklistDefinitionOut(ORMModel):
    id: uuid.UUID
    key: str
    title: str
    description: str | None
    version_label: str
    excel_template_path: str | None
    meta: dict[str, Any]
    created_at: datetime


class ChecklistItemOut(ORMModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: uuid.UUID
    definition_id: uuid.UUID
    item_key: str
    prompt: str
    method: str
    depends_on_references: bool
    excel_cell: str | None
    sort_order: int
    item_schema: dict[str, Any] = Field(
        validation_alias="schema_json",
        serialization_alias="item_schema",
    )


class StartChecklistBody(BaseModel):
    document_version_id: uuid.UUID
    definition_key: str = "software_code_standard"
    pinned_standard_version_ids: list[str] = Field(default_factory=list)
    external_evidence_document_version_ids: list[str] = Field(default_factory=list)


class ChecklistAnswerOut(ORMModel):
    id: uuid.UUID
    run_id: uuid.UUID
    item_id: uuid.UUID
    state: str
    confidence: float | None
    rationale: str | None
    ai_proposal: dict[str, Any]
    human_decision: str | None
    chapter_text: str | None
    comment_text: str | None
    excel_answer_cell: str | None
    excel_chapter_cell: str | None
    excel_comment_cell: str | None
    created_at: datetime


class EvidenceLinkOut(ORMModel):
    id: uuid.UUID
    checklist_answer_id: uuid.UUID | None
    document_version_id: uuid.UUID | None
    quote: str
    locator: dict[str, Any]


class ChecklistRunOut(ORMModel):
    id: uuid.UUID
    project_id: uuid.UUID
    definition_id: uuid.UUID
    document_version_id: uuid.UUID
    status: str
    started_at: datetime | None
    finished_at: datetime | None
    meta: dict[str, Any]
    created_at: datetime


class HumanDecisionBody(BaseModel):
    decision: Literal["accept", "reject", "override", "defer"]
    override_state: str | None = None
    change_rationale: str | None = None
    chapter_text: str | None = None
    comment_text: str | None = None
    status_value: str | None = Field(
        default=None,
        description="Optional Status cell value; never auto-set to Closed from AI",
    )
    reviewed_item: str | None = None
    reviewer_user_id: uuid.UUID | None = None


class StartExportBody(BaseModel):
    mode: Literal["draft", "reviewer_approved"] = "draft"


class ExportOut(ORMModel):
    id: uuid.UUID
    project_id: uuid.UUID
    checklist_run_id: uuid.UUID | None
    review_id: uuid.UUID | None
    storage_path: str
    template_path: str | None
    content_sha256: str | None
    status: str
    meta: dict[str, Any]
    created_at: datetime


class ReviewerDecisionOut(ORMModel):
    id: uuid.UUID
    review_item_id: uuid.UUID
    reviewer_user_id: uuid.UUID | None
    decision: str
    override_state: str | None
    comment: str | None
    created_at: datetime


@router.post("/checklists/seed/software-code-standard", response_model=ChecklistDefinitionOut)
async def seed_software_code_standard(db: AsyncSession = Depends(get_db)) -> ChecklistDefinition:
    definition = await seed_catalog(db)
    await db.commit()
    await db.refresh(definition)
    return definition


@router.get("/checklists", response_model=list[ChecklistDefinitionOut])
async def list_checklists(db: AsyncSession = Depends(get_db)) -> list[ChecklistDefinition]:
    return list(await db.scalars(select(ChecklistDefinition).order_by(ChecklistDefinition.key)))


@router.get("/checklists/{key}", response_model=ChecklistDefinitionOut)
async def get_checklist(key: str, db: AsyncSession = Depends(get_db)) -> ChecklistDefinition:
    row = await db.scalar(select(ChecklistDefinition).where(ChecklistDefinition.key == key))
    if not row:
        raise HTTPException(status_code=404, detail="checklist not found — POST seed first")
    return row


@router.get("/checklists/{key}/items", response_model=list[ChecklistItemOut])
async def list_items(key: str, db: AsyncSession = Depends(get_db)) -> list[ChecklistItem]:
    definition = await db.scalar(select(ChecklistDefinition).where(ChecklistDefinition.key == key))
    if not definition:
        raise HTTPException(status_code=404, detail="checklist not found")
    return list(
        await db.scalars(
            select(ChecklistItem)
            .where(ChecklistItem.definition_id == definition.id)
            .order_by(ChecklistItem.sort_order.asc())
        )
    )


@router.get("/checklists/catalog/software-code-standard/meta")
async def catalog_meta() -> dict[str, Any]:
    """Expose scaffold gap info without claiming template files exist."""
    data = load_catalog_file()
    return {
        "key": data["key"],
        "version_label": data["version_label"],
        "item_count": len(data["items"]),
        "template_gap": data.get("template_gap"),
        "cell_mapping": data.get("cell_mapping"),
        "excel_template_path": data.get("excel_template_path"),
    }


@router.post(
    "/projects/{project_id}/checklist-runs",
    response_model=JobOut,
    status_code=status.HTTP_202_ACCEPTED,
)
async def start_checklist_run(
    project_id: uuid.UUID,
    body: StartChecklistBody,
    db: AsyncSession = Depends(get_db),
) -> Any:
    project = await db.get(Project, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="project not found")
    version = await db.get(DocumentVersion, body.document_version_id)
    if not version:
        raise HTTPException(status_code=404, detail="document version not found")
    document = await db.get(Document, version.document_id)
    if not document or document.project_id != project_id:
        raise HTTPException(status_code=400, detail="document version not in project")

    # Ensure catalog seeded
    definition = await db.scalar(
        select(ChecklistDefinition).where(ChecklistDefinition.key == body.definition_key)
    )
    if definition is None and body.definition_key == "software_code_standard":
        await seed_catalog(db)

    job = await enqueue_job(
        db,
        job_type=JobType.CHECKLIST_REVIEW,
        payload={
            "project_id": str(project_id),
            "document_version_id": str(body.document_version_id),
            "definition_key": body.definition_key,
            "pinned_standard_version_ids": body.pinned_standard_version_ids,
            "external_evidence_document_version_ids": body.external_evidence_document_version_ids,
        },
        project_id=project_id,
        idempotency_key=make_idempotency_key(
            JobType.CHECKLIST_REVIEW,
            project_id,
            body.document_version_id,
            body.definition_key,
            version.content_sha256,
        ),
    )
    if job.status == "succeeded":
        job.status = "queued"
        job.result = {}
    await db.commit()
    await db.refresh(job)
    return job


@router.get("/checklist-runs/{run_id}", response_model=ChecklistRunOut)
async def get_run(run_id: uuid.UUID, db: AsyncSession = Depends(get_db)) -> ChecklistRun:
    run = await db.get(ChecklistRun, run_id)
    if not run:
        raise HTTPException(status_code=404, detail="checklist run not found")
    return run


@router.get("/checklist-runs/{run_id}/answers", response_model=list[ChecklistAnswerOut])
async def list_answers(
    run_id: uuid.UUID, db: AsyncSession = Depends(get_db)
) -> list[ChecklistAnswer]:
    run = await db.get(ChecklistRun, run_id)
    if not run:
        raise HTTPException(status_code=404, detail="checklist run not found")
    return list(
        await db.scalars(select(ChecklistAnswer).where(ChecklistAnswer.run_id == run_id))
    )


@router.get(
    "/checklist-answers/{answer_id}/evidence",
    response_model=list[EvidenceLinkOut],
)
async def list_answer_evidence(
    answer_id: uuid.UUID, db: AsyncSession = Depends(get_db)
) -> list[EvidenceLink]:
    answer = await db.get(ChecklistAnswer, answer_id)
    if not answer:
        raise HTTPException(status_code=404, detail="answer not found")
    return list(
        await db.scalars(
            select(EvidenceLink).where(EvidenceLink.checklist_answer_id == answer_id)
        )
    )


@router.get("/checklist-runs/{run_id}/view")
async def run_view(run_id: uuid.UUID, db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    """UI payload: item results, evidence, related ref findings, human decision + export hooks."""
    run = await db.get(ChecklistRun, run_id)
    if not run:
        raise HTTPException(status_code=404, detail="checklist run not found")
    definition = await db.get(ChecklistDefinition, run.definition_id)
    items = {
        i.id: i
        for i in (
            await db.scalars(
                select(ChecklistItem).where(ChecklistItem.definition_id == run.definition_id)
            )
        ).all()
    }
    answers = (
        await db.scalars(select(ChecklistAnswer).where(ChecklistAnswer.run_id == run_id))
    ).all()
    payload = []
    for ans in answers:
        item = items.get(ans.item_id)
        links = (
            await db.scalars(
                select(EvidenceLink).where(EvidenceLink.checklist_answer_id == ans.id)
            )
        ).all()
        schema_cells = (item.schema_json or {}).get("excel_cells") if item else {}
        decisions = await list_decisions_for_answer(db, ans.id)
        ref_findings = await related_reference_findings_for_answer(db, ans)
        payload.append(
            {
                "answer_id": str(ans.id),
                "item_key": item.item_key if item else None,
                "question": item.prompt if item else None,
                "method": item.method if item else None,
                "state": ans.state,
                "human_decision": ans.human_decision,
                "ai_proposal": ans.ai_proposal,
                "rationale": ans.rationale,
                "chapter_text": ans.chapter_text,
                "comment_text": ans.comment_text,
                "excel_cells": {
                    "answer": ans.excel_answer_cell or (schema_cells or {}).get("answer"),
                    "chapter": ans.excel_chapter_cell or (schema_cells or {}).get("chapter"),
                    "comment": ans.excel_comment_cell or (schema_cells or {}).get("comment"),
                    "references": (schema_cells or {}).get("references"),
                    "reviewed_item": (schema_cells or {}).get("reviewed_item"),
                    "status": (schema_cells or {}).get("status"),
                },
                "evidence": [
                    {"id": str(l.id), "quote": l.quote, "locator": l.locator} for l in links
                ],
                "related_reference_findings": ref_findings,
                "reviewer_decisions": [
                    ReviewerDecisionOut.model_validate(d).model_dump(mode="json")
                    for d in decisions
                ],
            }
        )
    template_ok = False
    template_error = None
    if definition and definition.excel_template_path:
        try:
            resolve_template_path(definition)
            template_ok = True
        except FileNotFoundError as exc:
            template_error = str(exc)
    return {
        "run": ChecklistRunOut.model_validate(run).model_dump(mode="json"),
        "definition_key": definition.key if definition else None,
        "template_gap": (definition.meta or {}).get("template_gap") if definition else None,
        "cell_mapping": (definition.meta or {}).get("cell_mapping") if definition else None,
        "excel_template_ready": template_ok,
        "excel_template_error": template_error,
        "pinned_standard_version_ids": (run.meta or {}).get("pinned_standard_version_ids"),
        "items": payload,
    }


@router.post("/checklist-answers/{answer_id}/decision")
async def post_human_decision(
    answer_id: uuid.UUID,
    body: HumanDecisionBody,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Record a reviewer decision; ai_proposal remains untouched (extras on raw_model_output)."""
    try:
        result = await record_human_decision(
            db,
            answer_id=answer_id,
            decision=body.decision,
            override_state=body.override_state,
            change_rationale=body.change_rationale,
            chapter_text=body.chapter_text,
            comment_text=body.comment_text,
            status_value=body.status_value,
            reviewed_item=body.reviewed_item,
            reviewer_user_id=body.reviewer_user_id,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    await db.commit()
    return result


@router.get(
    "/checklist-answers/{answer_id}/decisions",
    response_model=list[ReviewerDecisionOut],
)
async def get_answer_decisions(
    answer_id: uuid.UUID, db: AsyncSession = Depends(get_db)
) -> list[ReviewerDecision]:
    answer = await db.get(ChecklistAnswer, answer_id)
    if not answer:
        raise HTTPException(status_code=404, detail="answer not found")
    return await list_decisions_for_answer(db, answer_id)


@router.get("/checklist-answers/{answer_id}/reference-findings")
async def get_answer_reference_findings(
    answer_id: uuid.UUID, db: AsyncSession = Depends(get_db)
) -> list[dict[str, Any]]:
    answer = await db.get(ChecklistAnswer, answer_id)
    if not answer:
        raise HTTPException(status_code=404, detail="answer not found")
    return await related_reference_findings_for_answer(db, answer)


@router.post(
    "/checklist-runs/{run_id}/export",
    response_model=JobOut,
    status_code=status.HTTP_202_ACCEPTED,
)
async def start_export(
    run_id: uuid.UUID,
    body: StartExportBody,
    db: AsyncSession = Depends(get_db),
) -> Any:
    """Enqueue export job — fills a copy of the template; never mutates the original."""
    settings = get_settings()
    run = await db.get(ChecklistRun, run_id)
    if not run:
        raise HTTPException(status_code=404, detail="checklist run not found")
    definition = await db.get(ChecklistDefinition, run.definition_id)
    if not definition:
        raise HTTPException(status_code=404, detail="checklist definition not found")
    try:
        template_path = resolve_template_path(definition)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    export_id = uuid.uuid4()
    rel = f"{run.project_id}/{export_id}.xlsx"
    storage_path = str(Path(settings.export_dir) / rel)
    export = Export(
        id=export_id,
        project_id=run.project_id,
        checklist_run_id=run.id,
        storage_path=storage_path,
        template_path=str(template_path),
        status="pending",
        meta={"mode": body.mode},
    )
    db.add(export)
    await db.flush()

    job = await enqueue_job(
        db,
        job_type=JobType.EXPORT,
        payload={
            "export_id": str(export.id),
            "checklist_run_id": str(run.id),
            "mode": body.mode,
        },
        project_id=run.project_id,
        idempotency_key=make_idempotency_key(
            JobType.EXPORT, run.id, body.mode, export.id
        ),
    )
    await db.commit()
    await db.refresh(job)
    return job


@router.get("/exports/{export_id}", response_model=ExportOut)
async def get_export(export_id: uuid.UUID, db: AsyncSession = Depends(get_db)) -> Export:
    export = await db.get(Export, export_id)
    if not export:
        raise HTTPException(status_code=404, detail="export not found")
    return export


@router.get("/checklist-runs/{run_id}/exports", response_model=list[ExportOut])
async def list_run_exports(
    run_id: uuid.UUID, db: AsyncSession = Depends(get_db)
) -> list[Export]:
    run = await db.get(ChecklistRun, run_id)
    if not run:
        raise HTTPException(status_code=404, detail="checklist run not found")
    return list(
        await db.scalars(
            select(Export)
            .where(Export.checklist_run_id == run_id)
            .order_by(Export.created_at.desc())
        )
    )


@router.get("/exports/{export_id}/download")
async def download_export(
    export_id: uuid.UUID, db: AsyncSession = Depends(get_db)
) -> FileResponse:
    export = await db.get(Export, export_id)
    if not export:
        raise HTTPException(status_code=404, detail="export not found")
    if export.status != "ready":
        raise HTTPException(status_code=409, detail=f"export not ready (status={export.status})")
    path = Path(export.storage_path)
    if not path.is_file():
        raise HTTPException(status_code=404, detail="export file missing on disk")
    return FileResponse(
        path,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        filename=f"checklist-export-{export_id}.xlsx",
    )
