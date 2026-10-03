"""Reference / document-id normalization helpers (Phase 1).

Rules are intentionally conservative and unit-tested. Later phases may extend
patterns without breaking the public normalize_reference_key contract.
"""

from __future__ import annotations

import re
import unicodedata

_WS_RE = re.compile(r"\s+")
_PUNCT_RE = re.compile(r"[^\w]+", re.UNICODE)
# Common doc id fragments: IEC 61508-3:2010, DO-178C, MIL-STD-498, ESD-XXX-001 Rev B
_VERSION_RE = re.compile(
    r"(?i)\b(?:rev(?:ision)?|ver(?:sion)?|ed(?:ition)?)\s*[:.]?\s*([A-Za-z0-9.]+)\b"
)
_YEAR_RE = re.compile(r"\b((?:19|20)\d{2})\b")
_CLAUSE_RE = re.compile(
    r"(?i)(?:\b(?:clause|section|madde|bölüm)\b|§)\s*([0-9]+(?:\.[0-9]+)*)"
)


def collapse_ws(value: str) -> str:
    return _WS_RE.sub(" ", (value or "").replace("\xa0", " ")).strip()


def normalize_reference_key(raw: str) -> str:
    """Loose key for matching: NFKC, lower, strip punctuation noise, collapse ws."""
    s = unicodedata.normalize("NFKC", raw or "")
    s = collapse_ws(s).lower()
    s = s.replace("§", " clause ")
    s = _PUNCT_RE.sub(" ", s)
    return collapse_ws(s)


def extract_version_guess(raw: str) -> str | None:
    text = collapse_ws(raw or "")
    m = _VERSION_RE.search(text)
    if m:
        return m.group(1)
    years = _YEAR_RE.findall(text)
    if years:
        return years[-1]
    return None


def extract_clause_guess(raw: str) -> str | None:
    m = _CLAUSE_RE.search(raw or "")
    return m.group(1) if m else None


def normalize_alias(alias: str) -> str:
    return normalize_reference_key(alias)
