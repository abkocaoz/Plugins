"""Phase 6: SECI cross-document comparison across pinned document versions."""

from __future__ import annotations

import uuid

from app.core.enums import ChecklistAnswerState
from app.services.checklist_catalog import CATALOG_DIR, load_catalog_file
from app.services.evidence import EvidenceItem, EvidencePack, merge_evidence_packs
from app.services.seci_rules import run_seci_cross_document, run_seci_traceability


def _pack(
    texts: list[str],
    *,
    doc_type: str,
    project_id: uuid.UUID | None = None,
    version_id: uuid.UUID | None = None,
) -> EvidencePack:
    pid = project_id or uuid.uuid4()
    vid = version_id or uuid.uuid4()
    items = []
    for i, t in enumerate(texts):
        items.append(
            EvidenceItem(
                evidence_id=f"ev_{doc_type}_{i}_{vid.hex[:6]}",
                document_version_id=vid,
                project_id=pid,
                quote=t,
                locator={"kind": "unit", "doc_type": doc_type, "extra": {"doc_type": doc_type}},
                revision="1",
                content_sha256="sha",
            )
        )
    return EvidencePack(
        project_id=pid,
        document_version_id=vid,
        version_label="1",
        content_sha256="sha",
        items=items,
        items_by_version={str(vid): list(items)},
        doc_types_by_version={str(vid): doc_type},
    )


def test_seci_catalog_scaffold():
    data = load_catalog_file(key="seci")
    assert data["key"] == "seci"
    assert data["template_gap"]["claimed_template_file_count"] == 0
    assert (CATALOG_DIR / "fixtures" / "seci_synthetic_v1.xlsx").is_file()
    methods = {i["method"] for i in data["items"]}
    assert "cross_document" in methods
    assert "traceability" in methods


def test_seci_ids_present_in_pinned_icd():
    pid = uuid.uuid4()
    seci = _pack(
        [
            "The system shall use SIG-100 for speed.",
            "PARAM-200 shall be reported to the bus.",
        ],
        doc_type="seci",
        project_id=pid,
    )
    icd = _pack(
        [
            "SIG-100 | Speed | float | m/s",
            "PARAM-200 | Report | int | N/A",
        ],
        doc_type="data_icd",
        project_id=pid,
    )
    merged = merge_evidence_packs(seci, [(icd, "data_icd")])
    assert len(merged.pinned_document_version_ids) == 1
    result = run_seci_cross_document(
        "seci_ids_in_peer_docs",
        {
            "source_doc_types": ["seci"],
            "target_doc_types": ["icd", "data_icd"],
            "id_pattern": r"(?i)\b(?:SIG|PARAM|ICD)-[A-Z0-9]+\b",
            "requires_pinned_peers": True,
        },
        merged,
    )
    assert result.state == ChecklistAnswerState.YES
    assert "2" in result.rationale or "All" in result.rationale


def test_seci_ids_missing_in_peer_is_no():
    pid = uuid.uuid4()
    seci = _pack(
        ["Shall publish SIG-999 telemetry."],
        doc_type="seci",
        project_id=pid,
    )
    icd = _pack(
        ["SIG-001 | Other | float | m/s"],
        doc_type="data_icd",
        project_id=pid,
    )
    merged = merge_evidence_packs(seci, [(icd, "data_icd")])
    result = run_seci_cross_document(
        "seci_ids_in_peer_docs",
        {
            "source_doc_types": ["seci"],
            "target_doc_types": ["data_icd"],
            "requires_pinned_peers": True,
        },
        merged,
    )
    assert result.state == ChecklistAnswerState.NO


def test_seci_without_peers_insufficient():
    seci = _pack(["Shall use SIG-100."], doc_type="seci")
    result = run_seci_cross_document(
        "seci_ids_in_peer_docs",
        {
            "source_doc_types": ["seci"],
            "target_doc_types": ["data_icd"],
            "requires_pinned_peers": True,
        },
        seci,
    )
    assert result.state == ChecklistAnswerState.INSUFFICIENT_EVIDENCE


def test_pinned_versions_available():
    pid = uuid.uuid4()
    primary = _pack(["SECI body"], doc_type="seci", project_id=pid)
    peer = _pack(["ICD body SIG-1 | x | int | N/A"], doc_type="data_icd", project_id=pid)
    merged = merge_evidence_packs(primary, [(peer, "data_icd")])
    ok = run_seci_cross_document("seci_pinned_versions_available", {}, merged)
    assert ok.state == ChecklistAnswerState.YES

    alone = run_seci_cross_document("seci_pinned_versions_available", {}, primary)
    assert alone.state == ChecklistAnswerState.INSUFFICIENT_EVIDENCE


def test_shall_trace_to_peers():
    pid = uuid.uuid4()
    seci = _pack(
        ["The interface shall report airspeed on SIG-100."],
        doc_type="seci",
        project_id=pid,
    )
    design = _pack(
        ["Design covers airspeed reporting via SIG-100 channel."],
        doc_type="source",
        project_id=pid,
    )
    merged = merge_evidence_packs(seci, [(design, "source")])
    result = run_seci_traceability(
        "seci_shall_trace_to_peers",
        {"peer_doc_types": ["source", "design", "data_icd"]},
        merged,
    )
    assert result.state == ChecklistAnswerState.YES
