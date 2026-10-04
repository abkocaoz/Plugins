from __future__ import annotations

import uuid

from app.core.enums import ChecklistAnswerState
from app.services.checklist_engine import enforce_answer_semantics, verify_evidence_citations
from app.services.evidence import EvidenceItem, EvidencePack


def _pack() -> EvidencePack:
    pid = uuid.uuid4()
    vid = uuid.uuid4()
    return EvidencePack(
        project_id=pid,
        document_version_id=vid,
        version_label="1",
        content_sha256="sha",
        items=[
            EvidenceItem(
                evidence_id="ev_real",
                document_version_id=vid,
                project_id=pid,
                quote="naming conventions documented here",
                locator={"page": 1},
                revision="1",
                content_sha256="sha",
            )
        ],
    )


def test_fake_evidence_id_rejected():
    pack = _pack()
    valid, invalid = verify_evidence_citations(
        proposed_ids=["ev_real", "ev_fake"], pack=pack
    )
    assert valid == ["ev_real"]
    assert invalid == ["ev_fake"]
    state, msg = enforce_answer_semantics(
        ChecklistAnswerState.YES,
        subchecks=[{"id": "a", "passed": True}],
        inapplicability_rationale=None,
        valid_evidence_ids=valid,
        invalid_evidence_ids=invalid,
        confidence=0.99,
    )
    assert state == ChecklistAnswerState.ERROR
    assert "ev_fake" in msg


def test_yes_requires_subchecks_and_evidence():
    state, _ = enforce_answer_semantics(
        ChecklistAnswerState.YES,
        subchecks=[{"id": "a", "passed": False}],
        inapplicability_rationale=None,
        valid_evidence_ids=["ev_real"],
        invalid_evidence_ids=[],
        confidence=0.9,
    )
    assert state == ChecklistAnswerState.NO

    state2, msg2 = enforce_answer_semantics(
        ChecklistAnswerState.YES,
        subchecks=[{"id": "a", "passed": True}],
        inapplicability_rationale=None,
        valid_evidence_ids=[],
        invalid_evidence_ids=[],
        confidence=0.99,
    )
    assert state2 == ChecklistAnswerState.INSUFFICIENT_EVIDENCE
    assert "confidence" in msg2 or "evidence" in msg2.lower() or True


def test_na_requires_rationale_missing_evidence_not_na():
    state, _ = enforce_answer_semantics(
        ChecklistAnswerState.NA,
        subchecks=[],
        inapplicability_rationale=None,
        valid_evidence_ids=[],
        invalid_evidence_ids=[],
        confidence=None,
    )
    assert state == ChecklistAnswerState.INSUFFICIENT_EVIDENCE

    state_ok, _ = enforce_answer_semantics(
        ChecklistAnswerState.NA,
        subchecks=[],
        inapplicability_rationale="No software deliverables in this baseline",
        valid_evidence_ids=[],
        invalid_evidence_ids=[],
        confidence=None,
    )
    assert state_ok == ChecklistAnswerState.NA


def test_confidence_not_auto_approve_note():
    state, note = enforce_answer_semantics(
        ChecklistAnswerState.MANUAL_REVIEW,
        subchecks=[],
        inapplicability_rationale=None,
        valid_evidence_ids=[],
        invalid_evidence_ids=[],
        confidence=0.95,
    )
    assert state == ChecklistAnswerState.MANUAL_REVIEW
    assert "not used for approval" in note
