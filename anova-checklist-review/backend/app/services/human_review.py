"""Phase 5: record reviewer decisions separately from ai_proposal."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from app.models.entities import (
    AuditEvent,
    ChecklistAnswer,
    ChecklistRun,
    EvidenceLink,
    ExtractedReference,
    ReferenceFinding,
    Review,
    ReviewerDecision,
    ReviewItem,
)

ALLOWED_STATES = frozenset(
    {"YES", "NO", "NA", "INSUFFICIENT_EVIDENCE", "MANUAL_REVIEW", "ERROR"}
)
ALLOWED_DECISIONS = frozenset({"accept", "reject", "override", "defer"})


async def ensure_checklist_review(
    session: AsyncSession, run: ChecklistRun
) -> Review:
    candidates = (
        await session.scalars(
            select(Review).where(Review.checklist_run_id == run.id)
        )
    ).all()
    for existing in candidates:
        if (existing.meta or {}).get("kind") == "checklist_human_review":
            return existing
    review = Review(
        id=uuid.uuid4(),
        project_id=run.project_id,
        checklist_run_id=run.id,
        title=f"Human review — checklist run {run.id}",
        status="open",
        meta={"kind": "checklist_human_review"},
    )
    session.add(review)
    await session.flush()
    return review


async def ensure_review_item_for_answer(
    session: AsyncSession, review: Review, answer: ChecklistAnswer
) -> ReviewItem:
    existing = await session.scalar(
        select(ReviewItem).where(
            ReviewItem.review_id == review.id,
            ReviewItem.checklist_answer_id == answer.id,
        )
    )
    if existing:
        return existing
    item = ReviewItem(
        id=uuid.uuid4(),
        review_id=review.id,
        checklist_answer_id=answer.id,
        status="open",
    )
    session.add(item)
    await session.flush()
    return item


async def record_human_decision(
    session: AsyncSession,
    *,
    answer_id: uuid.UUID,
    decision: str,
    override_state: str | None = None,
    change_rationale: str | None = None,
    chapter_text: str | None = None,
    comment_text: str | None = None,
    status_value: str | None = None,
    reviewed_item: str | None = None,
    reviewer_user_id: uuid.UUID | None = None,
) -> dict[str, Any]:
    if decision not in ALLOWED_DECISIONS:
        raise ValueError(f"decision must be one of {sorted(ALLOWED_DECISIONS)}")

    answer = await session.get(ChecklistAnswer, answer_id)
    if answer is None:
        raise LookupError("answer not found")
    run = await session.get(ChecklistRun, answer.run_id)
    if run is None:
        raise LookupError("checklist run not found")

    review = await ensure_checklist_review(session, run)
    review_item = await ensure_review_item_for_answer(session, review, answer)

    # Resolve effective human state without mutating ai_proposal payload contents
    ai_proposed = (answer.ai_proposal or {}).get("proposed_state") or answer.state
    if decision == "accept":
        human_state = ai_proposed
    elif decision == "override":
        if not override_state or override_state not in ALLOWED_STATES:
            raise ValueError(f"override_state must be one of {sorted(ALLOWED_STATES)}")
        human_state = override_state
    elif decision == "reject":
        human_state = override_state or "MANUAL_REVIEW"
        if human_state not in ALLOWED_STATES:
            raise ValueError(f"override_state must be one of {sorted(ALLOWED_STATES)}")
    else:  # defer
        human_state = None

    rd = ReviewerDecision(
        id=uuid.uuid4(),
        review_item_id=review_item.id,
        reviewer_user_id=reviewer_user_id,
        decision=decision,
        override_state=human_state,
        comment=change_rationale,
    )
    session.add(rd)

    # Keep ai_proposal untouched; stash export extras on raw_model_output.human_export
    raw = dict(answer.raw_model_output or {})
    human_export = dict(raw.get("human_export") or {})
    if status_value is not None:
        # Never invent Closed from AI — only explicit human status_value
        human_export["status"] = status_value
    if reviewed_item is not None:
        human_export["reviewed_item"] = reviewed_item
    human_export["decision"] = decision
    human_export["decided_at"] = datetime.now(timezone.utc).isoformat()
    if change_rationale:
        human_export["change_rationale"] = change_rationale
    raw["human_export"] = human_export
    answer.raw_model_output = raw
    flag_modified(answer, "raw_model_output")

    if human_state is not None:
        answer.human_decision = human_state
        answer.state = human_state
    if chapter_text is not None:
        answer.chapter_text = chapter_text
    if comment_text is not None:
        answer.comment_text = comment_text
    elif change_rationale and decision in {"override", "reject"}:
        # Append rationale into comment when not explicitly provided
        base = answer.comment_text or answer.rationale or ""
        answer.comment_text = (
            f"{base} | Reviewer ({decision}): {change_rationale}".strip(" |")
        )

    review_item.status = "resolved" if decision != "defer" else "deferred"
    review_item.notes = change_rationale

    session.add(
        AuditEvent(
            id=uuid.uuid4(),
            project_id=run.project_id,
            actor_user_id=reviewer_user_id,
            action="checklist_answer.human_decision",
            entity_type="checklist_answer",
            entity_id=str(answer.id),
            details={
                "decision": decision,
                "human_decision": answer.human_decision,
                "ai_proposed": ai_proposed,
                "change_rationale": change_rationale,
                "reviewer_decision_id": str(rd.id),
            },
        )
    )
    await session.flush()
    return {
        "answer_id": str(answer.id),
        "review_id": str(review.id),
        "review_item_id": str(review_item.id),
        "reviewer_decision_id": str(rd.id),
        "decision": decision,
        "human_decision": answer.human_decision,
        "ai_proposal": answer.ai_proposal,
        "state": answer.state,
        "change_rationale": change_rationale,
    }


async def related_reference_findings_for_answer(
    session: AsyncSession, answer: ChecklistAnswer
) -> list[dict[str, Any]]:
    """Findings for the same document version as the checklist run (compact)."""
    run = await session.get(ChecklistRun, answer.run_id)
    if run is None:
        return []
    refs = (
        await session.scalars(
            select(ExtractedReference).where(
                ExtractedReference.document_version_id == run.document_version_id
            )
        )
    ).all()
    out: list[dict[str, Any]] = []
    for ref in refs:
        findings = (
            await session.scalars(
                select(ReferenceFinding).where(ReferenceFinding.extracted_reference_id == ref.id)
            )
        ).all()
        for f in findings:
            out.append(
                {
                    "finding_id": str(f.id),
                    "ref": ref.doc_id_guess or (ref.raw_text or "")[:200],
                    "stated_version": ref.version_guess,
                    "status": f.status,
                    "check_type": f.check_type,
                    "message": (f.message or "")[:500],
                    "location": ref.locator,
                    "blocks_dependent_items": f.blocks_dependent_items,
                }
            )
    return out


async def answer_evidence_payload(
    session: AsyncSession, answer_id: uuid.UUID
) -> list[dict[str, Any]]:
    links = (
        await session.scalars(
            select(EvidenceLink).where(EvidenceLink.checklist_answer_id == answer_id)
        )
    ).all()
    return [
        {
            "id": str(l.id),
            "quote": l.quote,
            "locator": l.locator,
            "document_version_id": str(l.document_version_id) if l.document_version_id else None,
        }
        for l in links
    ]


async def list_decisions_for_answer(
    session: AsyncSession, answer_id: uuid.UUID
) -> list[ReviewerDecision]:
    items = (
        await session.scalars(
            select(ReviewItem).where(ReviewItem.checklist_answer_id == answer_id)
        )
    ).all()
    if not items:
        return []
    ids = [i.id for i in items]
    return list(
        await session.scalars(
            select(ReviewerDecision)
            .where(ReviewerDecision.review_item_id.in_(ids))
            .order_by(ReviewerDecision.created_at.desc())
        )
    )

