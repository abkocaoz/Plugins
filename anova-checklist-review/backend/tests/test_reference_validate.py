from __future__ import annotations

import uuid

from app.core.enums import ReferenceStatus
from app.models.entities import ExtractedReference, ReferenceMatch
from app.services.reference_validate import (
    FindingDraft,
    _bibliographic_findings,
    _consistency_findings,
    _suggested_fix,
)


def test_suggested_fix_never_auto_applies():
    s = _suggested_fix("align_revision", cited_revision="A", catalog_revision="B")
    assert s["auto_apply"] is False


def test_consistency_conflicting_revisions():
    v = uuid.uuid4()
    a = ExtractedReference(
        id=uuid.uuid4(),
        document_version_id=v,
        raw_text="DO-178C Rev A",
        doc_id_guess="DO-178C",
        version_guess="A",
        locator={"page": 1},
        extraction_method="t",
        structured={},
    )
    b = ExtractedReference(
        id=uuid.uuid4(),
        document_version_id=v,
        raw_text="DO-178C Rev B",
        doc_id_guess="DO-178C",
        version_guess="B",
        locator={"page": 2},
        extraction_method="t",
        structured={},
    )
    findings = _consistency_findings(a, [a, b])
    assert any(f.status == ReferenceStatus.VERSION_MISMATCH for f in findings)
    assert all(f.details.get("suggested_fix", {}).get("auto_apply") is False for f in findings if f.details.get("suggested_fix"))


def test_version_mismatch_bibliographic():
    from app.models.entities import StandardCatalog, StandardVersion

    ref = ExtractedReference(
        id=uuid.uuid4(),
        document_version_id=uuid.uuid4(),
        raw_text="DO-178C Rev A",
        doc_id_guess="DO-178C",
        version_guess="A",
        locator={},
        extraction_method="t",
        structured={},
    )
    sel = ReferenceMatch(
        id=uuid.uuid4(),
        extracted_reference_id=ref.id,
        standard_version_id=uuid.uuid4(),
        match_method="id_revision",
        meta={"canonical_key": "DO-178C", "version_label": "B"},
    )
    std = StandardCatalog(
        id=uuid.uuid4(),
        canonical_key="DO-178C",
        title="Software Considerations",
        publisher="RTCA",
        meta={},
    )
    std_ver = StandardVersion(
        id=sel.standard_version_id,
        standard_id=std.id,
        version_label="B",
        meta={},
    )
    findings = _bibliographic_findings(ref, sel, std, std_ver)
    assert any(f.status == ReferenceStatus.VERSION_MISMATCH for f in findings)
    fix = next(f for f in findings if f.status == ReferenceStatus.VERSION_MISMATCH).details[
        "suggested_fix"
    ]
    assert fix["auto_apply"] is False
