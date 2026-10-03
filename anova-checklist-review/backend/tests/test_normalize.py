from app.services.normalize import (
    extract_clause_guess,
    extract_version_guess,
    normalize_alias,
    normalize_reference_key,
)


def test_normalize_reference_key_basic():
    assert normalize_reference_key("  IEC  61508-3:2010 ") == "iec 61508 3 2010"
    assert normalize_reference_key("DO-178C") == "do 178c"


def test_normalize_alias_matches_key():
    assert normalize_alias("Mil-Std-498") == normalize_reference_key("MIL STD 498")


def test_extract_version_guess():
    assert extract_version_guess("ESD-001 Rev B") == "B"
    assert extract_version_guess("IEC 61508-3:2010") == "2010"
    assert extract_version_guess("plain title") is None


def test_extract_clause_guess():
    assert extract_clause_guess("see Clause 4.2.3 for details") == "4.2.3"
    assert extract_clause_guess("§5.1") == "5.1"
    assert extract_clause_guess("madde 3.2") == "3.2"
    assert extract_clause_guess("no clause here") is None
