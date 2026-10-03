from app.services.extraction import ExtractedUnit, ExtractionIssue, Locator
from app.services.reference_extract import extract_references_from_units


def test_extract_from_references_section():
    units = [
        ExtractedUnit(
            text="3 References",
            locator=Locator(kind="docx_paragraph", paragraph=1),
        ),
        ExtractedUnit(
            text="DO-178C, Software Considerations in Airborne Systems, Rev B",
            locator=Locator(kind="docx_paragraph", paragraph=2),
        ),
        ExtractedUnit(
            text="MIL-STD-498 Rev A",
            locator=Locator(kind="docx_paragraph", paragraph=3),
        ),
    ]
    cands, gaps = extract_references_from_units(units)
    assert len(cands) >= 2
    assert any(c.doc_id and "178" in c.doc_id for c in cands)
    assert any(c.section_kind == "references_section" for c in cands)


def test_extract_body_citation_with_clause():
    units = [
        ExtractedUnit(
            text="Design shall follow DO-178C, Rev B, Clause 5.2.2 for requirements.",
            locator=Locator(kind="pdf_page", page=4),
        )
    ]
    cands, _ = extract_references_from_units(units)
    assert cands
    assert cands[0].doc_id
    assert cands[0].clause in {None, "5.2.2"} or cands[0].clause == "5.2.2"
    # clause may be on same candidate via parse
    assert any(c.clause == "5.2.2" or "5.2.2" in c.raw_text for c in cands)


def test_ocr_gap_recorded_when_empty():
    units: list[ExtractedUnit] = []
    issues = [
        ExtractionIssue(
            code="OCR_NEEDED",
            message="scanned",
            locator={"page": 1},
        )
    ]
    cands, gaps = extract_references_from_units(units, issues)
    assert cands == []
    assert any(g["code"] == "REFERENCE_EXTRACTION_BLOCKED" for g in gaps)


def test_does_not_invent_fields():
    units = [
        ExtractedUnit(
            text="References\nSome informal note without identifiers",
            locator=Locator(kind="docx_paragraph", paragraph=1),
        )
    ]
    cands, _ = extract_references_from_units(units)
    for c in cands:
        # If no doc id parsed, revision/publisher must remain unset
        if c.doc_id is None:
            assert c.revision is None
            assert c.publisher is None
