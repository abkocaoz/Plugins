"""Reference review APIs (Phase 3) — before checklist evaluation."""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from app.api.deps import require_dev_token
from app.core.job_types import JobType
from app.db.session import get_db
from app.models.entities import (
    Document,
    DocumentVersion,
    ExtractedReference,
    ReferenceFinding,
    ReferenceMatch,
    Review,
    ReviewItem,
)
from app.schemas.common import JobOut, ORMModel
from app.services.jobs import enqueue_job, make_idempotency_key
from datetime import datetime

router = APIRouter(prefix="/api/v1", tags=["references"], dependencies=[Depends(require_dev_token)])


class ExtractedReferenceOut(ORMModel):
    id: uuid.UUID
    document_version_id: uuid.UUID
    raw_text: str
    normalized_key: str | None
    doc_id_guess: str | None
    title_guess: str | None
    version_guess: str | None
    clause_guess: str | None
    publisher_guess: str | None
    supplement_guess: str | None
    date_guess: str | None
    section_kind: str | None
    normalization_version: str | None
    resolution_state: str
    selected_match_id: uuid.UUID | None
    context_span: str | None
    locator: dict[str, Any]
    extraction_method: str
    structured: dict[str, Any]
    created_at: datetime


class ReferenceMatchOut(ORMModel):
    id: uuid.UUID
    extracted_reference_id: uuid.UUID
    standard_version_id: uuid.UUID | None
    document_version_id: uuid.UUID | None
    score: float | None
    rank: int
    match_method: str
    meta: dict[str, Any]


class ReferenceFindingOut(ORMModel):
    id: uuid.UUID
    extracted_reference_id: uuid.UUID
    reference_match_id: uuid.UUID | None
    status: str
    check_type: str
    message: str
    details: dict[str, Any]
    blocks_dependent_items: bool


class SelectMatchBody(BaseModel):
    match_id: uuid.UUID


class MissingReferenceOut(BaseModel):
    extracted_reference_id: uuid.UUID
    searched_id: str | None
    searched_revision: str | None
    searched_supplement: str | None
    locations: list[dict[str, Any]]
    alternate_versions_found: list[dict[str, Any]]
    raw_text: str
    resolution_state: str


class ReferenceReviewOut(BaseModel):
    review_id: uuid.UUID
    project_id: uuid.UUID
    document_version_id: uuid.UUID | None
    status: str
    title: str
    pinned_standard_version_ids: list[str]
    blocks_independent_checklist: bool
    items: list[dict[str, Any]]
    summary: dict[str, int]


@router.get(
    "/document-versions/{version_id}/references",
    response_model=list[ExtractedReferenceOut],
)
async def list_references(
    version_id: uuid.UUID, db: AsyncSession = Depends(get_db)
) -> list[ExtractedReference]:
    version = await db.get(DocumentVersion, version_id)
    if not version:
        raise HTTPException(status_code=404, detail="document version not found")
    rows = (
        await db.scalars(
            select(ExtractedReference)
            .where(ExtractedReference.document_version_id == version_id)
            .order_by(ExtractedReference.created_at.asc())
        )
    ).all()
    return list(rows)


@router.get(
    "/references/{ref_id}/matches",
    response_model=list[ReferenceMatchOut],
)
async def list_matches(ref_id: uuid.UUID, db: AsyncSession = Depends(get_db)) -> list[ReferenceMatch]:
    ref = await db.get(ExtractedReference, ref_id)
    if not ref:
        raise HTTPException(status_code=404, detail="reference not found")
    rows = (
        await db.scalars(
            select(ReferenceMatch)
            .where(ReferenceMatch.extracted_reference_id == ref_id)
            .order_by(ReferenceMatch.rank.asc())
        )
    ).all()
    return list(rows)


@router.get(
    "/references/{ref_id}/findings",
    response_model=list[ReferenceFindingOut],
)
async def list_findings(
    ref_id: uuid.UUID, db: AsyncSession = Depends(get_db)
) -> list[ReferenceFinding]:
    ref = await db.get(ExtractedReference, ref_id)
    if not ref:
        raise HTTPException(status_code=404, detail="reference not found")
    rows = (
        await db.scalars(
            select(ReferenceFinding).where(ReferenceFinding.extracted_reference_id == ref_id)
        )
    ).all()
    return list(rows)


@router.post("/references/{ref_id}/select-match", response_model=ExtractedReferenceOut)
async def select_match(
    ref_id: uuid.UUID, body: SelectMatchBody, db: AsyncSession = Depends(get_db)
) -> ExtractedReference:
    """User selects among candidates (unspecified/ambiguous). Does not mutate source doc."""
    ref = await db.get(ExtractedReference, ref_id)
    if not ref:
        raise HTTPException(status_code=404, detail="reference not found")
    match = await db.get(ReferenceMatch, body.match_id)
    if not match or match.extracted_reference_id != ref.id:
        raise HTTPException(status_code=404, detail="match not found for this reference")
    ref.selected_match_id = match.id
    ref.resolution_state = "user_selected"
    version = await db.get(DocumentVersion, ref.document_version_id)
    document = await db.get(Document, version.document_id) if version else None
    if version and document:
        await enqueue_job(
            db,
            job_type=JobType.REFERENCE_VALIDATION,
            payload={
                "document_version_id": str(version.id),
                "only_reference_ids": [str(ref.id)],
            },
            project_id=document.project_id,
            idempotency_key=make_idempotency_key(
                JobType.REFERENCE_VALIDATION,
                version.id,
                f"user_select:{ref.id}:{match.id}",
            ),
        )
    await db.commit()
    await db.refresh(ref)
    return ref


@router.get(
    "/document-versions/{version_id}/missing-references",
    response_model=list[MissingReferenceOut],
)
async def list_missing_references(
    version_id: uuid.UUID, db: AsyncSession = Depends(get_db)
) -> list[MissingReferenceOut]:
    version = await db.get(DocumentVersion, version_id)
    if not version:
        raise HTTPException(status_code=404, detail="document version not found")
    refs = (
        await db.scalars(
            select(ExtractedReference).where(
                ExtractedReference.document_version_id == version_id,
                ExtractedReference.resolution_state.in_(["missing_source", "needs_user"]),
            )
        )
    ).all()
    out: list[MissingReferenceOut] = []
    for ref in refs:
        findings = (
            await db.scalars(
                select(ReferenceFinding).where(
                    ReferenceFinding.extracted_reference_id == ref.id,
                    ReferenceFinding.status.in_(
                        ["MISSING_SOURCE", "VERSION_UNSPECIFIED", "AMBIGUOUS_MATCH"]
                    ),
                )
            )
        ).all()
        alt: list[dict[str, Any]] = []
        locations = [ref.locator]
        for f in findings:
            details = f.details or {}
            alt = details.get("alternate_versions_found") or alt
            if details.get("locations"):
                locations = details["locations"]
        matches = (
            await db.scalars(
                select(ReferenceMatch)
                .where(ReferenceMatch.extracted_reference_id == ref.id)
                .order_by(ReferenceMatch.rank.asc())
            )
        ).all()
        if not alt:
            alt = [
                {
                    "standard_version_id": str(m.standard_version_id),
                    "version_label": (m.meta or {}).get("version_label"),
                    "canonical_key": (m.meta or {}).get("canonical_key"),
                    "match_method": m.match_method,
                    "score": m.score,
                }
                for m in matches
            ]
        out.append(
            MissingReferenceOut(
                extracted_reference_id=ref.id,
                searched_id=ref.doc_id_guess,
                searched_revision=ref.version_guess,
                searched_supplement=ref.supplement_guess,
                locations=locations,
                alternate_versions_found=alt,
                raw_text=ref.raw_text,
                resolution_state=ref.resolution_state,
            )
        )
    return out


@router.post(
    "/document-versions/{version_id}/reference-resolution",
    response_model=JobOut,
    status_code=status.HTTP_202_ACCEPTED,
)
async def trigger_resolution(
    version_id: uuid.UUID, db: AsyncSession = Depends(get_db)
) -> Any:
    version = await db.get(DocumentVersion, version_id)
    if not version:
        raise HTTPException(status_code=404, detail="document version not found")
    document = await db.get(Document, version.document_id)
    if not document:
        raise HTTPException(status_code=404, detail="document not found")
    job = await enqueue_job(
        db,
        job_type=JobType.REFERENCE_RESOLUTION,
        payload={"document_version_id": str(version.id)},
        project_id=document.project_id,
        idempotency_key=make_idempotency_key(
            JobType.REFERENCE_RESOLUTION, version.id, version.content_sha256, "manual"
        ),
    )
    if job.status == "succeeded":
        job.status = "queued"
        job.result = {}
    await db.commit()
    await db.refresh(job)
    return job


@router.get(
    "/document-versions/{version_id}/reference-review",
    response_model=ReferenceReviewOut,
)
async def get_reference_review(
    version_id: uuid.UUID, db: AsyncSession = Depends(get_db)
) -> ReferenceReviewOut:
    """Reference review screen payload — before checklist. Missing refs do not block independent work."""
    version = await db.get(DocumentVersion, version_id)
    if not version:
        raise HTTPException(status_code=404, detail="document version not found")
    document = await db.get(Document, version.document_id)
    if not document:
        raise HTTPException(status_code=404, detail="document not found")

    reviews = (
        await db.scalars(
            select(Review).where(Review.project_id == document.project_id)
        )
    ).all()
    review = None
    for r in reviews:
        meta = r.meta or {}
        if (
            meta.get("kind") == "reference_validation"
            and meta.get("document_version_id") == str(version_id)
        ):
            review = r
            break
    if review is None:
        raise HTTPException(
            status_code=404,
            detail="reference review not ready — wait for reference_validation job",
        )

    items = (
        await db.scalars(select(ReviewItem).where(ReviewItem.review_id == review.id))
    ).all()
    payload_items = []
    summary: dict[str, int] = {}
    for item in items:
        finding = (
            await db.get(ReferenceFinding, item.reference_finding_id)
            if item.reference_finding_id
            else None
        )
        ref = (
            await db.get(ExtractedReference, finding.extracted_reference_id)
            if finding
            else None
        )
        st = finding.status if finding else "UNKNOWN"
        summary[st] = summary.get(st, 0) + 1
        payload_items.append(
            {
                "review_item_id": str(item.id),
                "status": item.status,
                "finding": {
                    "id": str(finding.id) if finding else None,
                    "status": finding.status if finding else None,
                    "check_type": finding.check_type if finding else None,
                    "message": finding.message if finding else None,
                    "details": finding.details if finding else None,
                    "blocks_dependent_items": finding.blocks_dependent_items if finding else False,
                },
                "reference": {
                    "id": str(ref.id) if ref else None,
                    "raw_text": ref.raw_text if ref else None,
                    "doc_id": ref.doc_id_guess if ref else None,
                    "revision": ref.version_guess if ref else None,
                    "locator": ref.locator if ref else None,
                    "resolution_state": ref.resolution_state if ref else None,
                },
            }
        )

    meta = review.meta or {}
    return ReferenceReviewOut(
        review_id=review.id,
        project_id=review.project_id,
        document_version_id=uuid.UUID(meta["document_version_id"])
        if meta.get("document_version_id")
        else None,
        status=review.status,
        title=review.title,
        pinned_standard_version_ids=list(meta.get("pinned_standard_version_ids") or []),
        blocks_independent_checklist=bool(meta.get("blocks_independent_checklist", False)),
        items=payload_items,
        summary=summary,
    )


@router.post(
    "/reference-reviews/{review_id}/pin-versions",
)
async def pin_versions(
    review_id: uuid.UUID,
    body: dict[str, list[str]],
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    review = await db.get(Review, review_id)
    if not review:
        raise HTTPException(status_code=404, detail="review not found")
    meta = dict(review.meta or {})
    if meta.get("kind") != "reference_validation":
        raise HTTPException(status_code=400, detail="not a reference validation review")
    meta["pinned_standard_version_ids"] = list(body.get("standard_version_ids") or [])
    review.meta = meta
    flag_modified(review, "meta")
    await db.commit()
    return {
        "review_id": str(review.id),
        "pinned_standard_version_ids": meta["pinned_standard_version_ids"],
    }
