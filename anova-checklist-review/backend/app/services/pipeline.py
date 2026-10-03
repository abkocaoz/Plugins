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
    ExtractedReference,
    Job,
    Project,
    Review,
    ReviewItem,
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
    if job.job_type == JobType.REFERENCE_RESOLUTION:
        return await run_reference_resolution(session, settings, job)
    if job.job_type == JobType.REFERENCE_VALIDATION:
        return await run_reference_validation(session, settings, job)
    if job.job_type == JobType.CHECKLIST_REVIEW:
        return await run_checklist_review_job(session, settings, job)
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

    ref_job = await _enqueue_reference_resolution(session, document, version)
    return {
        "chunk_count": count,
        "collection": settings.qdrant_collection_project_docs,
        "reference_resolution_job_id": str(ref_job.id),
    }


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

    # After indexing a missing source, re-run only affected reference checks
    affected = await _enqueue_affected_reference_checks(
        session, document.project_id, standard.canonical_key, std_version.id
    )
    return {
        "chunk_count": count,
        "collection": settings.qdrant_collection_standards,
        "affected_reference_jobs": affected,
    }


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


async def _enqueue_reference_resolution(
    session: AsyncSession, document: Document, version: DocumentVersion
) -> Job:
    return await enqueue_job(
        session,
        job_type=JobType.REFERENCE_RESOLUTION,
        payload={"document_version_id": str(version.id)},
        project_id=document.project_id,
        idempotency_key=make_idempotency_key(
            JobType.REFERENCE_RESOLUTION, version.id, version.content_sha256
        ),
    )


async def _enqueue_reference_validation(
    session: AsyncSession,
    project_id: uuid.UUID,
    version: DocumentVersion,
    *,
    only_reference_ids: list[uuid.UUID] | None = None,
) -> Job:
    payload: dict[str, Any] = {"document_version_id": str(version.id)}
    if only_reference_ids:
        payload["only_reference_ids"] = [str(i) for i in only_reference_ids]
    key_extra = ",".join(sorted(payload.get("only_reference_ids") or ["all"]))
    return await enqueue_job(
        session,
        job_type=JobType.REFERENCE_VALIDATION,
        payload=payload,
        project_id=project_id,
        idempotency_key=make_idempotency_key(
            JobType.REFERENCE_VALIDATION, version.id, version.content_sha256, key_extra
        ),
    )


async def run_reference_resolution(
    session: AsyncSession, settings: Settings, job: Job
) -> dict[str, Any]:
    from app.services.reference_extract import extract_references_from_units
    from app.services.reference_match import (
        fetch_semantic_candidates,
        load_catalog_index,
        load_project_approved_versions,
        match_reference,
        persist_match_decision,
    )

    version_id = uuid.UUID(job.payload["document_version_id"])
    version = await session.get(DocumentVersion, version_id)
    if version is None:
        raise RuntimeError("document_version not found")
    document = await session.get(Document, version.document_id)
    if document is None:
        raise RuntimeError("document missing")

    # Respect indexing dependency
    indexing = (version.meta or {}).get("indexing") or {}
    if indexing.get("status") != "ok":
        raise RuntimeError("reference_resolution requires successful indexing first")

    units, raw = await _load_extraction_units(version)
    issues = ((version.meta or {}).get("extraction") or {}).get("issues") or raw.get("issues") or []
    candidates, gaps = extract_references_from_units(units, issues)

    # Replace prior extracted refs for this version (idempotent re-run)
    old_refs = (
        await session.scalars(
            select(ExtractedReference).where(
                ExtractedReference.document_version_id == version.id
            )
        )
    ).all()
    for row in old_refs:
        await session.delete(row)
    await session.flush()

    catalog = await load_catalog_index(session)
    approved = await load_project_approved_versions(session, document.project_id)

    created_ids: list[str] = []
    auto = 0
    needs_user = 0
    missing = 0
    for cand in candidates:
        ref = ExtractedReference(
            id=uuid.uuid4(),
            document_version_id=version.id,
            raw_text=cand.raw_text,
            normalized_key=cand.normalized_key,
            doc_id_guess=cand.doc_id,
            title_guess=cand.title,
            version_guess=cand.revision,
            clause_guess=cand.clause,
            context_span=cand.context_span,
            locator=cand.locator,
            extraction_method=cand.extraction_method,
            publisher_guess=cand.publisher,
            supplement_guess=cand.supplement,
            date_guess=cand.date_year,
            section_kind=cand.section_kind,
            normalization_version=cand.normalization_version,
            resolution_state="pending",
            structured={
                "gaps": cand.gaps,
                "normalization_version": cand.normalization_version,
            },
        )
        session.add(ref)
        await session.flush()

        semantic = await fetch_semantic_candidates(settings, ref, catalog)
        decision = match_reference(ref, catalog, approved, semantic_candidates=semantic)
        await persist_match_decision(session, ref, decision)
        created_ids.append(str(ref.id))
        if decision.resolution_state == "auto_selected":
            auto += 1
        elif decision.resolution_state == "needs_user":
            needs_user += 1
        elif decision.resolution_state == "missing_source":
            missing += 1

    meta = dict(version.meta or {})
    meta["reference_resolution"] = {
        "status": "ok",
        "count": len(created_ids),
        "auto_selected": auto,
        "needs_user": needs_user,
        "missing_source": missing,
        "gaps": gaps,
        "resolved_at": datetime.now(timezone.utc).isoformat(),
    }
    version.meta = meta
    flag_modified(version, "meta")

    val_job = await _enqueue_reference_validation(session, document.project_id, version)
    return {
        "extracted_reference_ids": created_ids,
        "counts": {
            "total": len(created_ids),
            "auto_selected": auto,
            "needs_user": needs_user,
            "missing_source": missing,
        },
        "validation_job_id": str(val_job.id),
    }


async def run_reference_validation(
    session: AsyncSession, settings: Settings, job: Job
) -> dict[str, Any]:
    from app.services.reference_validate import persist_findings, validate_reference

    version_id = uuid.UUID(job.payload["document_version_id"])
    version = await session.get(DocumentVersion, version_id)
    if version is None:
        raise RuntimeError("document_version not found")
    document = await session.get(Document, version.document_id)
    if document is None:
        raise RuntimeError("document missing")

    resolution = (version.meta or {}).get("reference_resolution") or {}
    if resolution.get("status") != "ok" and not job.payload.get("only_reference_ids"):
        raise RuntimeError("reference_validation requires reference_resolution first")

    refs = (
        await session.scalars(
            select(ExtractedReference).where(
                ExtractedReference.document_version_id == version.id
            )
        )
    ).all()
    only = job.payload.get("only_reference_ids")
    if only:
        only_set = {uuid.UUID(str(x)) for x in only}
        refs = [r for r in refs if r.id in only_set]

    source_text = None
    if version.extracted_text_path and Path(version.extracted_text_path).is_file():
        source_text = Path(version.extracted_text_path).read_text(
            encoding="utf-8", errors="replace"
        )

    finding_count = 0
    for ref in refs:
        drafts = await validate_reference(
            session,
            ref,
            project_id=document.project_id,
            sibling_refs=list(refs),
            source_text=source_text,
        )
        created = await persist_findings(session, ref, drafts, replace=True)
        finding_count += len(created)

    # Ensure / refresh a reference review run with pinned approved versions
    review = await _ensure_reference_review(session, document.project_id, version)

    meta = dict(version.meta or {})
    meta["reference_validation"] = {
        "status": "ok",
        "finding_count": finding_count,
        "review_id": str(review.id),
        "validated_at": datetime.now(timezone.utc).isoformat(),
        "partial": bool(only),
    }
    version.meta = meta
    flag_modified(version, "meta")
    return {
        "finding_count": finding_count,
        "review_id": str(review.id),
        "reference_count": len(refs),
    }


async def _ensure_reference_review(
    session: AsyncSession, project_id: uuid.UUID, version: DocumentVersion
) -> Review:
    from app.services.reference_match import load_project_approved_versions

    approved = await load_project_approved_versions(session, project_id)
    pinned = sorted(str(x) for x in approved)

    existing = (
        await session.scalars(
            select(Review).where(
                Review.project_id == project_id,
                Review.status == "open",
            )
        )
    ).all()
    review = None
    for r in existing:
        meta = r.meta or {}
        if (
            meta.get("kind") == "reference_validation"
            and meta.get("document_version_id") == str(version.id)
        ):
            review = r
            break
    if review is None:
        review = Review(
            id=uuid.uuid4(),
            project_id=project_id,
            title=f"Reference validation — {version.version_label}",
            status="open",
            meta={
                "kind": "reference_validation",
                "document_version_id": str(version.id),
                "pinned_standard_version_ids": pinned,
                "blocks_independent_checklist": False,
            },
        )
        session.add(review)
        await session.flush()
    else:
        meta = dict(review.meta or {})
        meta["pinned_standard_version_ids"] = pinned
        review.meta = meta
        flag_modified(review, "meta")

    # Sync review_items to current findings
    from app.models.entities import ReferenceFinding

    refs = (
        await session.scalars(
            select(ExtractedReference).where(
                ExtractedReference.document_version_id == version.id
            )
        )
    ).all()
    findings = (
        await session.scalars(
            select(ReferenceFinding).where(
                ReferenceFinding.extracted_reference_id.in_([r.id for r in refs] or [uuid.uuid4()])
            )
        )
    ).all() if refs else []

    old_items = (
        await session.scalars(select(ReviewItem).where(ReviewItem.review_id == review.id))
    ).all()
    for item in old_items:
        await session.delete(item)
    await session.flush()

    for f in findings:
        session.add(
            ReviewItem(
                id=uuid.uuid4(),
                review_id=review.id,
                reference_finding_id=f.id,
                status="open" if f.status != "VERIFIED" else "resolved",
                notes=None,
            )
        )
    await session.flush()
    return review


async def _enqueue_affected_reference_checks(
    session: AsyncSession,
    project_id: uuid.UUID,
    canonical_key: str,
    standard_version_id: uuid.UUID,
) -> list[str]:
    """Re-resolve/validate only refs that were missing this id (or same id)."""
    from app.services.normalize import normalize_doc_id

    key = normalize_doc_id(canonical_key)
    missing_refs = (
        await session.scalars(
            select(ExtractedReference).where(
                ExtractedReference.resolution_state.in_(["missing_source", "needs_user"]),
            )
        )
    ).all()
    affected_by_version: dict[uuid.UUID, list[uuid.UUID]] = {}
    for ref in missing_refs:
        if ref.doc_id_guess and normalize_doc_id(ref.doc_id_guess) == key:
            affected_by_version.setdefault(ref.document_version_id, []).append(ref.id)

    job_ids: list[str] = []
    for doc_version_id, ref_ids in affected_by_version.items():
        version = await session.get(DocumentVersion, doc_version_id)
        if version is None:
            continue
        # Re-run resolution for whole doc version (catalog changed), then validation for affected
        document = await session.get(Document, version.document_id)
        if document is None or document.project_id != project_id:
            continue
        res_job = await enqueue_job(
            session,
            job_type=JobType.REFERENCE_RESOLUTION,
            payload={"document_version_id": str(version.id)},
            project_id=project_id,
            idempotency_key=make_idempotency_key(
                JobType.REFERENCE_RESOLUTION,
                version.id,
                version.content_sha256,
                f"after_std:{standard_version_id}",
            ),
        )
        job_ids.append(str(res_job.id))
        # Note: validation is chained from resolution; ref_ids used when partial revalidate needed
        _ = ref_ids
    return job_ids


async def run_checklist_review_job(
    session: AsyncSession, settings: Settings, job: Job
) -> dict[str, Any]:
    from app.services.checklist_engine import run_checklist_review

    project_id = job.project_id or uuid.UUID(job.payload["project_id"])
    document_version_id = uuid.UUID(job.payload["document_version_id"])
    definition_key = job.payload.get("definition_key") or "software_code_standard"
    pinned = job.payload.get("pinned_standard_version_ids")
    external = job.payload.get("external_evidence_document_version_ids")
    return await run_checklist_review(
        session,
        settings,
        project_id=project_id,
        document_version_id=document_version_id,
        definition_key=definition_key,
        pinned_standard_version_ids=list(pinned) if pinned else None,
        external_evidence_document_version_ids=list(external) if external else None,
    )

