"""Thin convenience endpoints for the simplified /ui home flow."""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_dev_token
from app.core.config import Settings, get_settings
from app.core.job_types import JobType
from app.db.session import get_db
from app.models.entities import Document, DocumentVersion, Project
from app.services.checklist_catalog import (
    get_registry_entry,
    registry_entries,
    seed_catalog_by_key,
    seedable_catalog_paths,
)
from app.services.jobs import enqueue_job, make_idempotency_key

router = APIRouter(prefix="/api/v1", tags=["ui"], dependencies=[Depends(require_dev_token)])


class StartReviewBody(BaseModel):
    project_id: uuid.UUID
    document_version_id: uuid.UUID
    definition_key: str = "software_code_standard"
    pinned_document_version_ids: list[str] = Field(default_factory=list)


def _revision_row(doc: Document, ver: DocumentVersion) -> dict[str, Any]:
    return {
        "document_id": str(doc.id),
        "title": doc.title,
        "doc_type": doc.doc_type,
        "version_id": str(ver.id),
        "version_label": ver.version_label,
        "parse_status": ver.parse_status,
        "created_at": ver.created_at.isoformat() if ver.created_at else None,
        "is_current": doc.current_version_id == ver.id,
        "original_filename": (ver.meta or {}).get("original_filename"),
    }


async def _list_revisions(db: AsyncSession, project_id: uuid.UUID) -> list[dict[str, Any]]:
    docs = list(
        await db.scalars(
            select(Document)
            .where(Document.project_id == project_id)
            .order_by(Document.created_at.desc())
        )
    )
    out: list[dict[str, Any]] = []
    for doc in docs:
        versions = list(
            await db.scalars(
                select(DocumentVersion)
                .where(DocumentVersion.document_id == doc.id)
                .order_by(DocumentVersion.created_at.desc())
            )
        )
        for ver in versions:
            out.append(_revision_row(doc, ver))
    return out


def _checklist_options() -> list[dict[str, Any]]:
    options: list[dict[str, Any]] = []
    seedable = seedable_catalog_paths()
    for entry in registry_entries():
        key = entry.get("definition_key")
        if not key or not entry.get("seedable") or key not in seedable:
            continue
        options.append(
            {
                "definition_key": key,
                "title": entry.get("title") or key,
                "status": entry.get("status"),
                "notes": entry.get("notes"),
            }
        )
    return options


@router.get("/ui/home")
async def ui_home(
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    """Home-screen payload: default project, document revisions, seedable checklists."""
    project = await db.scalar(select(Project).where(Project.slug == "live-demo"))
    if project is None:
        project = await db.scalar(select(Project).order_by(Project.created_at.desc()))

    revisions: list[dict[str, Any]] = []
    if project is not None:
        revisions = await _list_revisions(db, project.id)

    token_hint = settings.dev_api_token if settings.auth_mode == "dev" else None
    return {
        "auth_mode": settings.auth_mode,
        "demo_mode": settings.demo_mode,
        "api_token_hint": token_hint,
        "project": (
            {
                "id": str(project.id),
                "slug": project.slug,
                "name": project.name,
            }
            if project
            else None
        ),
        "document_revisions": revisions,
        "checklists": _checklist_options(),
        "empty_hint": (
            None
            if revisions
            else "Henüz doküman yok. Dosya yükleyin veya örnek veri için demo bootstrap kullanın."
        ),
        "links": {
            "ui": "/ui",
            "references": "/ui/references",
            "checklist": "/ui/checklist",
            "demo_bootstrap": "/api/v1/demo/bootstrap",
        },
    }


@router.get("/projects/{project_id}/document-revisions")
async def list_document_revisions(
    project_id: uuid.UUID, db: AsyncSession = Depends(get_db)
) -> list[dict[str, Any]]:
    project = await db.get(Project, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="project not found")
    return await _list_revisions(db, project_id)


@router.post("/ui/start-review", status_code=status.HTTP_202_ACCEPTED)
async def start_review_from_selection(
    body: StartReviewBody,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Seed checklist if needed, ensure reference chain is queued, start checklist_review."""
    project = await db.get(Project, body.project_id)
    if not project:
        raise HTTPException(status_code=404, detail="project not found")

    version = await db.get(DocumentVersion, body.document_version_id)
    if not version:
        raise HTTPException(status_code=404, detail="document version not found")
    document = await db.get(Document, version.document_id)
    if not document or document.project_id != body.project_id:
        raise HTTPException(status_code=400, detail="document version not in project")

    definition_key = body.definition_key.replace("-", "_")
    entry = get_registry_entry(definition_key)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"unknown checklist: {definition_key}")
    if not entry.get("seedable") or definition_key not in seedable_catalog_paths():
        raise HTTPException(
            status_code=409,
            detail=f"checklist {definition_key!r} is not seedable (awaiting_template)",
        )

    await seed_catalog_by_key(db, definition_key, replace_items=False)

    extract_ready = version.parse_status in {"ok", "partial", "succeeded"}
    meta = version.meta or {}
    refs_done = bool((meta.get("reference_resolution") or {}).get("status"))

    reference_job_id = None
    if extract_ready and not refs_done:
        ref_job = await enqueue_job(
            db,
            job_type=JobType.REFERENCE_RESOLUTION,
            payload={"document_version_id": str(version.id)},
            project_id=body.project_id,
            idempotency_key=make_idempotency_key(
                JobType.REFERENCE_RESOLUTION,
                version.id,
                version.content_sha256,
                "ui-start",
            ),
        )
        reference_job_id = str(ref_job.id)

    checklist_job = await enqueue_job(
        db,
        job_type=JobType.CHECKLIST_REVIEW,
        payload={
            "project_id": str(body.project_id),
            "document_version_id": str(body.document_version_id),
            "definition_key": definition_key,
            "pinned_standard_version_ids": [],
            "pinned_document_version_ids": body.pinned_document_version_ids,
            "external_evidence_document_version_ids": [],
        },
        project_id=body.project_id,
        idempotency_key=make_idempotency_key(
            JobType.CHECKLIST_REVIEW,
            body.project_id,
            body.document_version_id,
            definition_key,
            version.content_sha256,
            ",".join(sorted(body.pinned_document_version_ids)),
            "ui-start",
        ),
    )
    if checklist_job.status == "succeeded":
        checklist_job.status = "queued"
        checklist_job.result = {}

    await db.commit()
    await db.refresh(checklist_job)

    checklist_qs = (
        f"?pid={body.project_id}&vid={body.document_version_id}"
        f"&dkey={definition_key}&job={checklist_job.id}"
    )
    refs_qs = f"?vid={body.document_version_id}&pid={body.project_id}"

    return {
        "project_id": str(body.project_id),
        "document_id": str(document.id),
        "document_title": document.title,
        "document_version_id": str(version.id),
        "version_label": version.version_label,
        "definition_key": definition_key,
        "definition_title": entry.get("title") or definition_key,
        "parse_status": version.parse_status,
        "extract_ready": extract_ready,
        "reference_job_id": reference_job_id,
        "checklist_job_id": str(checklist_job.id),
        "checklist_job_status": checklist_job.status,
        "message": (
            "İnceleme kuyruğa alındı."
            if extract_ready
            else "Extract henüz bitmedi; checklist job sırada bekleyebilir — birkaç saniye sonra yenileyin."
        ),
        "next": {
            "checklist": f"/ui/checklist{checklist_qs}",
            "references": f"/ui/references{refs_qs}",
            "home": "/ui",
        },
        "session": {
            "project_id": str(body.project_id),
            "document_version_id": str(version.id),
            "document_title": document.title,
            "definition_key": definition_key,
            "definition_title": entry.get("title") or definition_key,
            "checklist_job_id": str(checklist_job.id),
        },
    }
