from app.services.normalize import (
    NORMALIZATION_VERSION,
    extract_clause_guess,
    extract_version_guess,
    normalize_alias,
    normalize_doc_id,
    normalize_reference_key,
    normalize_revision,
    parse_reference,
)


def test_normalize_reference_key_basic():
    assert normalize_reference_key("  IEC  61508-3:2010 ") == "iec 61508 3 2010"
    assert normalize_reference_key("DO-178C") == "do 178c"


def test_normalize_alias_matches_key():
    assert normalize_alias("Mil-Std-498") == normalize_reference_key("MIL STD 498")


def test_extract_version_guess():
    assert extract_version_guess("ESD-XXX-001 Rev B") == "B"
    assert extract_version_guess("IEC 61508-3:2010") == "2010"
    assert extract_version_guess("plain title") is None


def test_extract_clause_guess():
    assert extract_clause_guess("see Clause 4.2.3 for details") == "4.2.3"
    assert extract_clause_guess("§5.1") == "5.1"
    assert extract_clause_guess("madde 3.2") == "3.2"
    assert extract_clause_guess("no clause here") is None


def test_parse_preserves_revision_vs_supplement():
    a = parse_reference("DO-178C Rev B")
    b = parse_reference("DO-178C Supp 1")
    assert a.doc_id == normalize_doc_id("DO-178C")
    assert a.revision == "B"
    assert a.supplement is None
    assert b.supplement == "1"
    assert b.revision is None
    assert a.id_revision_key != b.id_supplement_key
    assert a.normalization_version == NORMALIZATION_VERSION


def test_normalize_revision_does_not_collapse_letter_and_digit():
    assert normalize_revision("B") == "B"
    assert normalize_revision("2") == "2"
    assert normalize_revision("B") != normalize_revision("2")


def test_uncertain_fields_stay_none():
    p = parse_reference("see applicable guidance")
    assert p.doc_id is None
    assert p.revision is None
    assert p.title is None
