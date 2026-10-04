"""Versioned reference normalization (Phase 3).

Rules are conservative and unit-tested. Uncertain fields stay None — never invent.
Revision and supplement differences are preserved (not collapsed into one token).
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import asdict, dataclass

# Bump when normalization semantics change (stored on extracted_reference.meta).
NORMALIZATION_VERSION = "refnorm-v3.1"

_WS_RE = re.compile(r"\s+")
_PUNCT_RE = re.compile(r"[^\w]+", re.UNICODE)

# Doc IDs: DO-178C, MIL-STD-498, IEC 61508-3, ESD-XXX-001, ARP4754A
_DOC_ID_RE = re.compile(
    r"(?i)\b("
    r"(?:DO|ED|ARP|RTCA|EUROCAE)[-\s]?\d+[A-Z]?"
    r"|MIL[-\s]?STD[-\s]?\d+[A-Z]?"
    r"|IEC\s?\d+(?:-\d+)*(?:[:/]\d{4})?"
    r"|ISO\s?\d+(?:-\d+)*(?:[:/]\d{4})?"
    r"|IEEE\s?\d+(?:[.\-]\d+)*"
    r"|[A-Z]{2,6}[-_][A-Z0-9]{2,}(?:[-_][A-Z0-9]+)+"
    r")\b"
)

_REVISION_RE = re.compile(
    r"(?i)\b(?:rev(?:ision)?|ver(?:sion)?|ed(?:ition)?)\s*[:.]?\s*([A-Za-z0-9]+(?:\.[0-9]+)?)\b"
)
_SUPPLEMENT_RE = re.compile(
    r"(?i)\b(?:supp(?:lement)?|amdt|amend(?:ment)?|chg|change)\s*[:.]?\s*([A-Za-z0-9.]+)\b"
)
_YEAR_RE = re.compile(r"\b((?:19|20)\d{2})\b")
_CLAUSE_RE = re.compile(
    r"(?i)(?:\b(?:clause|section|madde|bölüm)\b|§)\s*([0-9]+(?:\.[0-9]+)*)"
)
_PUBLISHER_RE = re.compile(
    r"(?i)\b(RTCA|EUROCAE|IEC|ISO|IEEE|SAE|NASA|ESA|NATO|ARINC|FAA|EASA)\b"
)
# Title after em-dash / colon often follows doc id
_TITLE_AFTER_ID_RE = re.compile(
    r"(?i)^(?:see\s+|per\s+|according to\s+)?(?P<id>[A-Z0-9][A-Z0-9./\- ]{2,40}?)"
    r"(?:\s*[:–—-]\s*|\s+)(?P<title>[A-Z][^;,]{5,120})"
)


@dataclass(frozen=True)
class NormalizedReference:
    """Structured parse. Any uncertain field remains None."""

    normalization_version: str
    raw_text: str
    normalized_key: str
    doc_id: str | None = None
    title: str | None = None
    revision: str | None = None
    supplement: str | None = None
    publisher: str | None = None
    date_year: str | None = None
    clause: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)

    @property
    def id_revision_key(self) -> str | None:
        if not self.doc_id:
            return None
        rev = self.revision or ""
        return f"{normalize_doc_id(self.doc_id)}|rev:{rev}"

    @property
    def id_supplement_key(self) -> str | None:
        if not self.doc_id:
            return None
        return f"{normalize_doc_id(self.doc_id)}|supp:{self.supplement or ''}"


def collapse_ws(value: str) -> str:
    return _WS_RE.sub(" ", (value or "").replace("\xa0", " ")).strip()


def normalize_reference_key(raw: str) -> str:
    """Loose key for matching: NFKC, lower, strip punctuation noise, collapse ws."""
    s = unicodedata.normalize("NFKC", raw or "")
    s = collapse_ws(s).lower()
    s = s.replace("§", " clause ")
    s = _PUNCT_RE.sub(" ", s)
    return collapse_ws(s)


def normalize_doc_id(doc_id: str) -> str:
    """Normalize document id while keeping distinguishing letters (e.g. DO-178C)."""
    s = unicodedata.normalize("NFKC", doc_id or "")
    s = collapse_ws(s).upper()
    s = s.replace("_", "-")
    s = re.sub(r"\s+", "-", s)
    s = re.sub(r"-{2,}", "-", s)
    return s.strip("-")


def normalize_revision(rev: str | None) -> str | None:
    if rev is None:
        return None
    s = collapse_ws(str(rev)).upper()
    if not s:
        return None
    # Do not map "B" and "2" together; keep as-is after trim/case.
    return s


def normalize_supplement(supp: str | None) -> str | None:
    if supp is None:
        return None
    s = collapse_ws(str(supp)).upper()
    return s or None


def normalize_alias(alias: str) -> str:
    return normalize_reference_key(alias)


def extract_version_guess(raw: str) -> str | None:
    """Backward-compatible: revision first, else year."""
    parsed = parse_reference(raw)
    return parsed.revision or parsed.date_year


def extract_clause_guess(raw: str) -> str | None:
    return parse_reference(raw).clause


def parse_reference(raw: str) -> NormalizedReference:
    text = collapse_ws(unicodedata.normalize("NFKC", raw or ""))
    if not text:
        return NormalizedReference(
            normalization_version=NORMALIZATION_VERSION,
            raw_text="",
            normalized_key="",
        )

    doc_id = None
    m_id = _DOC_ID_RE.search(text)
    if m_id:
        doc_id = normalize_doc_id(m_id.group(1))

    revision = None
    m_rev = _REVISION_RE.search(text)
    if m_rev:
        revision = normalize_revision(m_rev.group(1))

    supplement = None
    m_supp = _SUPPLEMENT_RE.search(text)
    if m_supp:
        supplement = normalize_supplement(m_supp.group(1))

    clause = None
    m_cl = _CLAUSE_RE.search(text)
    if m_cl:
        clause = m_cl.group(1)

    publisher = None
    m_pub = _PUBLISHER_RE.search(text)
    if m_pub:
        publisher = m_pub.group(1).upper()

    date_year = None
    years = _YEAR_RE.findall(text)
    if years:
        # Prefer year attached after colon in standards (IEC …:2010)
        date_year = years[-1]

    title = None
    m_title = _TITLE_AFTER_ID_RE.search(text)
    if m_title and m_id:
        cand = collapse_ws(m_title.group("title"))
        # Drop trailing revision noise from title candidate
        cand = _REVISION_RE.sub("", cand)
        cand = _SUPPLEMENT_RE.sub("", cand)
        cand = collapse_ws(cand).strip(" -–—:")
        if len(cand) >= 5 and not _DOC_ID_RE.fullmatch(cand):
            title = cand

    return NormalizedReference(
        normalization_version=NORMALIZATION_VERSION,
        raw_text=text,
        normalized_key=normalize_reference_key(text),
        doc_id=doc_id,
        title=title,
        revision=revision,
        supplement=supplement,
        publisher=publisher,
        date_year=date_year,
        clause=clause,
    )
