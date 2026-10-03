"""Extract + index pipeline stages invoked by the job worker."""

from __future__ import annotations

import json
import logging
import uuid
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from app.core.config import Settings
from app.core.job_types import JobType
from app.models.entities import (
    Document,
    DocumentVersion,
    Job,
    Project,
    StandardCatalog,
    StandardVersion,
)
from app.services.chunking import chunk_units
from app.services.embedding_client import EmbeddingClient
from app.services.extraction import dumps_extraction, extract_document
from app.services.jobs import enqueue_job, make_idempotency_key
from app.services.qdrant_index import QdrantIndexer
from app.services.storage import write_extraction_artifact

logger = logging.getLogger(__name__)


async def process_job(session: AsyncSession, settings: Settings, job: Job) -> dict[str, Any]:
    if job.job_type == JobType.EXTRACT_DOCUMENT:
        return await run_extract_document(session, settings, job)
    if job.job_type == JobType.INDEX_DOCUMENT:
        return await run_index_document(session, settings, job)
    if job.job_type == JobType.INDEX_STANDARD:
        return await run_index_standard(session, settings, job)
    if job.job_type == JobType.REINDEX_PROJECT:
        return await run_reindex_project(session, settings, job)
    raise ValueError(f"Unknown job type: {job.job_type}")


async def run_extract_document(
    session: AsyncSession, settings: Settings, job: Job
) -> dict[str, Any]:
    version_id = uuid.UUID(job.payload["document_version_id"])
    version = await session.get(DocumentVersion, version_id)
    if version is None:
        raise RuntimeError(f"document_version {version_id} not found")
    document = await session.get(Document, version.document_id)
    if document is None:
        raise RuntimeError(f"document {version.document_id} not found")

    # Idempotent: same sha already extracted successfully
    meta = dict(version.meta or {})
    prev = meta.get("extraction") or {}
    if (
        prev.get("status") in {"ok", "partial"}
        and prev.get("content_sha256") == version.content_sha256
        and version.extracted_text_path
        and Path(version.extracted_text_path).is_file()
    ):
        await _enqueue_index_after_extract(session, document, version)
        return {"skipped": True, "reason": "already_extracted", "status": prev.get("status")}

    path = Path(version.storage_path)
    data = path.read_bytes()
    original_name = (meta.get("original_filename") or path.name).removeprefix("original__")
    result = extract_document(data, original_name, version.mime_type)

    json_path = write_extraction_artifact(
        Path(settings.upload_dir),
        document.project_id,
        document.id,
        version.id,
        "extraction.json",
        dumps_extraction(result),
    )
    text_path = write_extraction_artifact(
        Path(settings.upload_dir),
        document.project_id,
        document.id,
        version.id,
        "full_text.txt",
        result.full_text.encode("utf-8"),
    )

    version.extracted_text_path = str(text_path)
    version.parse_status = result.status
    meta["extraction"] = {
        "status": result.status,
        "format": result.format,
        "content_sha256": version.content_sha256,
        "issues": [asdict(i) for i in result.issues],
        "unit_count": len(result.units),
        "extraction_json_path": str(json_path),
        "extracted_at": datetime.now(timezone.utc).isoformat(),
    }
    version.meta = meta
    flag_modified(version, "meta")

    index_job = None
    if result.status != "failed":
        index_job = await _enqueue_index_after_extract(session, document, version)

    return {
        "parse_status": result.status,
        "unit_count": len(result.units),
        "issue_count": len(result.issues),
        "extraction_json_path": str(json_path),
        "index_job_id": str(index_job.id) if index_job else None,
    }


async def _enqueue_index_after_extract(
    session: AsyncSession, document: Document, version: DocumentVersion
) -> Job:
    # Standards go to standards collection when linked via standard_versions
    std_version_id = (version.meta or {}).get("standard_version_id")
    if document.doc_type == "standard" or std_version_id:
        jt = JobType.INDEX_STANDARD
        key = make_idempotency_key(
            jt, version.id, version.content_sha256, std_version_id or "auto"
        )
        payload = {
            "document_version_id": str(version.id),
            "standard_version_id": std_version_id,
        }
    else:
        jt = JobType.INDEX_DOCUMENT
        key = make_idempotency_key(jt, version.id, version.content_sha256)
        payload = {"document_version_id": str(version.id)}
    return await enqueue_job(
        session,
        job_type=jt,
        payload=payload,
        project_id=document.project_id,
        idempotency_key=key,
    )


async def _load_extraction_units(version: DocumentVersion) -> tuple[list, dict[str, Any]]:
    meta = version.meta or {}
    extraction = meta.get("extraction") or {}
    json_path = extraction.get("extraction_json_path")
    if not json_path or not Path(json_path).is_file():
        raise RuntimeError("extraction artifact missing; run extract_document first")
    data = json.loads(Path(json_path).read_text(encoding="utf-8"))
    from app.services.extraction import ExtractedUnit, Locator

    units = []
    for u in data.get("units") or []:
        loc_raw = u.get("locator") or {}
        units.append(
            ExtractedUnit(
                text=u.get("text") or "",
                locator=Locator(
                    kind=loc_raw.get("kind") or "unknown",
                    page=loc_raw.get("page"),
                    paragraph=loc_raw.get("paragraph"),
                    sheet=loc_raw.get("sheet"),
                    row=loc_raw.get("row"),
                    column=loc_raw.get("column"),
                    line_start=loc_raw.get("line_start"),
                    line_end=loc_raw.get("line_end"),
                    extra=loc_raw.get("extra") or {},
                ),
            )
        )
    return units, data


async def run_index_document(
    session: AsyncSession, settings: Settings, job: Job
) -> dict[str, Any]:
    version_id = uuid.UUID(job.payload["document_version_id"])
    version = await session.get(DocumentVersion, version_id)
    if version is None:
        raise RuntimeError(f"document_version {version_id} not found")
    document = await session.get(Document, version.document_id)
    if document is None:
        raise RuntimeError("document missing")

    units, _raw = await _load_extraction_units(version)
    chunks = chunk_units(
        units,
        chunk_size=settings.chunk_size_chars,
        overlap=settings.chunk_overlap_chars,
    )
    async with EmbeddingClient(settings) as emb:
        embeddings = await emb.embed([c.text for c in chunks])

    indexer = QdrantIndexer(settings)
    count = indexer.upsert_project_document_chunks(
        project_id=document.project_id,
        document_id=document.id,
        document_version_id=version.id,
        doc_type=document.doc_type,
        version_label=version.version_label,
        content_sha256=version.content_sha256,
        chunks=chunks,
        embeddings=embeddings,
    )

    meta = dict(version.meta or {})
    meta["indexing"] = {
        "status": "ok",
        "collection": settings.qdrant_collection_project_docs,
        "chunk_count": count,
        "content_sha256": version.content_sha256,
        "indexed_at": datetime.now(timezone.utc).isoformat(),
    }
    version.meta = meta
    flag_modified(version, "meta")
    return {"chunk_count": count, "collection": settings.qdrant_collection_project_docs}


async def run_index_standard(
    session: AsyncSession, settings: Settings, job: Job
) -> dict[str, Any]:
    version_id = uuid.UUID(job.payload["document_version_id"])
    version = await session.get(DocumentVersion, version_id)
    if version is None:
        raise RuntimeError(f"document_version {version_id} not found")
    document = await session.get(Document, version.document_id)
    if document is None:
        raise RuntimeError("document missing")

    std_version_id_raw = job.payload.get("standard_version_id") or (version.meta or {}).get(
        "standard_version_id"
    )
    if not std_version_id_raw:
        raise RuntimeError("standard_version_id required for index_standard")
    std_version = await session.get(StandardVersion, uuid.UUID(str(std_version_id_raw)))
    if std_version is None:
        raise RuntimeError("standard_version not found")
    standard = await session.get(StandardCatalog, std_version.standard_id)
    if standard is None:
        raise RuntimeError("standard_catalog not found")

    units, _raw = await _load_extraction_units(version)
    chunks = chunk_units(
        units,
        chunk_size=settings.chunk_size_chars,
        overlap=settings.chunk_overlap_chars,
    )
    async with EmbeddingClient(settings) as emb:
        embeddings = await emb.embed([c.text for c in chunks])

    indexer = QdrantIndexer(settings)
    count = indexer.upsert_standard_chunks(
        standard_id=standard.id,
        standard_version_id=std_version.id,
        document_version_id=version.id,
        canonical_key=standard.canonical_key,
        version_label=std_version.version_label,
        content_sha256=version.content_sha256,
        chunks=chunks,
        embeddings=embeddings,
    )

    meta = dict(version.meta or {})
    meta["indexing"] = {
        "status": "ok",
        "collection": settings.qdrant_collection_standards,
        "chunk_count": count,
        "standard_version_id": str(std_version.id),
        "content_sha256": version.content_sha256,
        "indexed_at": datetime.now(timezone.utc).isoformat(),
    }
    version.meta = meta
    flag_modified(version, "meta")
    # Keep document_version linkage on standard version
    if std_version.document_version_id != version.id:
        std_version.document_version_id = version.id
    return {"chunk_count": count, "collection": settings.qdrant_collection_standards}


async def run_reindex_project(
    session: AsyncSession, settings: Settings, job: Job
) -> dict[str, Any]:
    project_id = job.project_id or uuid.UUID(job.payload["project_id"])
    project = await session.get(Project, project_id)
    if project is None:
        raise RuntimeError("project not found")
    versions = (
        await session.scalars(
            select(DocumentVersion)
            .join(Document, Document.id == DocumentVersion.document_id)
            .where(Document.project_id == project_id)
        )
    ).all()
    enqueued = []
    for version in versions:
        document = await session.get(Document, version.document_id)
        if document is None:
            continue
        if version.parse_status in {"ok", "partial"}:
            j = await _enqueue_index_after_extract(session, document, version)
            enqueued.append(str(j.id))
        else:
            j = await enqueue_job(
                session,
                job_type=JobType.EXTRACT_DOCUMENT,
                payload={"document_version_id": str(version.id)},
                project_id=project_id,
                idempotency_key=make_idempotency_key(
                    JobType.EXTRACT_DOCUMENT, version.id, version.content_sha256
                ),
            )
            enqueued.append(str(j.id))
    return {"enqueued_jobs": enqueued, "version_count": len(versions)}
