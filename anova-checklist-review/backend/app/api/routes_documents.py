from __future__ import annotations

import mimetypes
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_dev_token
from app.core.config import Settings, get_settings
from app.core.job_types import JobType
from app.db.session import get_db
from app.models.entities import Document, DocumentVersion, Project
from app.schemas.common import DocumentOut, DocumentVersionOut, UploadResponse
from app.services.jobs import enqueue_job, make_idempotency_key
from app.services.storage import write_original

router = APIRouter(tags=["documents"], dependencies=[Depends(require_dev_token)])


@router.post(
    "/api/v1/projects/{project_id}/documents",
    response_model=UploadResponse,
    status_code=status.HTTP_201_CREATED,
)
async def upload_document(
    project_id: uuid.UUID,
    file: UploadFile = File(...),
    title: str | None = Form(default=None),
    doc_type: str = Form(default="source"),
    version_label: str = Form(default="1"),
    document_id: uuid.UUID | None = Form(default=None),
    standard_version_id: uuid.UUID | None = Form(default=None),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> UploadResponse:
    """Upload original file. Creates a new document or a new revision of an existing one."""
    project = await db.get(Project, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="project not found")

    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="empty file")

    filename = file.filename or "upload.bin"
    mime = file.content_type or mimetypes.guess_type(filename)[0]

    if document_id is not None:
        document = await db.get(Document, document_id)
        if not document or document.project_id != project_id:
            raise HTTPException(status_code=404, detail="document not found in project")
        # Separate revision: reject duplicate version_label
        clash = await db.scalar(
            select(DocumentVersion).where(
                DocumentVersion.document_id == document.id,
                DocumentVersion.version_label == version_label,
            )
        )
        if clash:
            raise HTTPException(
                status_code=409,
                detail=f"version_label '{version_label}' already exists; use a new revision label",
            )
    else:
        document = Document(
            id=uuid.uuid4(),
            project_id=project_id,
            title=title or Path(filename).stem,
            doc_type=doc_type,
            meta={},
        )
        db.add(document)
        await db.flush()

    version = DocumentVersion(
        id=uuid.uuid4(),
        document_id=document.id,
        version_label=version_label,
        storage_path="",  # filled after write
        content_sha256="",
        mime_type=mime,
        byte_size=len(data),
        parse_status="pending",
        meta={
            "original_filename": filename,
            "standard_version_id": str(standard_version_id) if standard_version_id else None,
        },
    )
    db.add(version)
    await db.flush()

    dest, digest = write_original(
        Path(settings.upload_dir),
        project_id,
        document.id,
        version.id,
        filename,
        data,
    )
    version.storage_path = str(dest)
    version.content_sha256 = digest
    document.current_version_id = version.id
    if title:
        document.title = title
    if doc_type:
        document.doc_type = doc_type

    job = await enqueue_job(
        db,
        job_type=JobType.EXTRACT_DOCUMENT,
        payload={"document_version_id": str(version.id)},
        project_id=project_id,
        idempotency_key=make_idempotency_key(
            JobType.EXTRACT_DOCUMENT, version.id, digest
        ),
    )
    await db.commit()
    await db.refresh(document)
    await db.refresh(version)
    await db.refresh(job)
    return UploadResponse(
        document=DocumentOut.model_validate(document),
        version=DocumentVersionOut.model_validate(version),
        extract_job_id=job.id,
    )


@router.get("/api/v1/projects/{project_id}/documents", response_model=list[DocumentOut])
async def list_documents(
    project_id: uuid.UUID, db: AsyncSession = Depends(get_db)
) -> list[Document]:
    rows = (
        await db.scalars(
            select(Document)
            .where(Document.project_id == project_id)
            .order_by(Document.created_at.desc())
        )
    ).all()
    return list(rows)


@router.get("/api/v1/documents/{document_id}", response_model=DocumentOut)
async def get_document(document_id: uuid.UUID, db: AsyncSession = Depends(get_db)) -> Document:
    document = await db.get(Document, document_id)
    if not document:
        raise HTTPException(status_code=404, detail="document not found")
    return document


@router.get(
    "/api/v1/documents/{document_id}/versions",
    response_model=list[DocumentVersionOut],
)
async def list_versions(
    document_id: uuid.UUID, db: AsyncSession = Depends(get_db)
) -> list[DocumentVersion]:
    document = await db.get(Document, document_id)
    if not document:
        raise HTTPException(status_code=404, detail="document not found")
    rows = (
        await db.scalars(
            select(DocumentVersion)
            .where(DocumentVersion.document_id == document_id)
            .order_by(DocumentVersion.created_at.desc())
        )
    ).all()
    return list(rows)


@router.get(
    "/api/v1/document-versions/{version_id}",
    response_model=DocumentVersionOut,
)
async def get_version(
    version_id: uuid.UUID, db: AsyncSession = Depends(get_db)
) -> DocumentVersion:
    version = await db.get(DocumentVersion, version_id)
    if not version:
        raise HTTPException(status_code=404, detail="document version not found")
    return version
