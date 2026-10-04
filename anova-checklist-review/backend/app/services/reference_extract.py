"""Extract bibliographic / clause references from document extraction units.

Looks for References / Applicable Documents sections, body citations,
and units tagged as table / footnote / header / footer when present.
Records OCR/extraction gaps without inventing citation fields.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Any

from app.services.extraction import ExtractedUnit, ExtractionIssue
from app.services.normalize import NORMALIZATION_VERSION, parse_reference

_SECTION_HEADER_RE = re.compile(
    r"(?i)^\s*(?:\d+(?:\.\d+)*\s+)?("
    r"references|"
    r"applicable\s+documents|"
    r"normative\s+references|"
    r"reference\s+documents|"
    r"cited\s+documents|"
    r"kaynaklar|"
    r"uygulanan\s+dok[uü]manlar"
    r")\s*$"
)

# Body citation patterns (conservative)
_CITATION_RES = [
    re.compile(
        r"(?i)\b(?:see|per|according to|ref(?:erence)?\.?|as defined in)\s+"
        r"([A-Z][A-Z0-9./\- ]{2,60}?(?:\s+Rev(?:ision)?\s*[A-Z0-9.]+)?)"
    ),
    re.compile(
        r"(?i)\b((?:DO|ED|ARP|MIL-STD|IEC|ISO|IEEE)[-\s]?\d+[A-Z0-9./\-]*)"
        r"(?:\s*,?\s*Rev(?:ision)?\s*([A-Z0-9.]+))?"
        r"(?:\s*,?\s*(?:Clause|Section|§)\s*([0-9]+(?:\.[0-9]+)*))?"
    ),
]

_BULLET_RE = re.compile(r"^\s*(?:[-*•]|\d+[.)])\s+")


@dataclass
class ExtractedRefCandidate:
    raw_text: str
    locator: dict[str, Any]
    section_kind: str
    extraction_method: str
    context_span: str | None = None
    # Structured fields — None when uncertain (never invented)
    doc_id: str | None = None
    title: str | None = None
    revision: str | None = None
    supplement: str | None = None
    publisher: str | None = None
    date_year: str | None = None
    clause: str | None = None
    normalized_key: str = ""
    normalization_version: str = NORMALIZATION_VERSION
    gaps: list[dict[str, Any]] = field(default_factory=list)

    def to_persist_dict(self) -> dict[str, Any]:
        return {
            "raw_text": self.raw_text,
            "locator": self.locator,
            "section_kind": self.section_kind,
            "extraction_method": self.extraction_method,
            "context_span": self.context_span,
            "doc_id": self.doc_id,
            "title": self.title,
            "revision": self.revision,
            "supplement": self.supplement,
            "publisher": self.publisher,
            "date_year": self.date_year,
            "clause": self.clause,
            "normalized_key": self.normalized_key,
            "normalization_version": self.normalization_version,
            "gaps": self.gaps,
        }


def _unit_section_kind(unit: ExtractedUnit, in_ref_section: bool) -> str:
    kind = (unit.locator.kind or "").lower()
    extra = unit.locator.extra or {}
    if "footnote" in kind or extra.get("region") == "footnote":
        return "footnote"
    if "header" in kind or extra.get("region") == "header":
        return "header"
    if "footer" in kind or extra.get("region") == "footer":
        return "footer"
    if "table" in kind or "xlsx" in kind or "csv" in kind:
        return "table"
    if in_ref_section:
        return "references_section"
    return "body"


def _build_candidate(
    raw: str,
    locator: dict[str, Any],
    section_kind: str,
    method: str,
    context: str | None,
    gaps: list[dict[str, Any]] | None = None,
) -> ExtractedRefCandidate | None:
    text = (raw or "").strip()
    if len(text) < 4:
        return None
    parsed = parse_reference(text)
    # Require at least a doc id or a long title-like string from a references section
    if not parsed.doc_id and section_kind not in {"references_section", "table"}:
        return None
    if not parsed.doc_id and section_kind in {"references_section", "table"} and len(text) < 8:
        return None
    return ExtractedRefCandidate(
        raw_text=text[:2000],
        locator=locator,
        section_kind=section_kind,
        extraction_method=method,
        context_span=(context or "")[:2000] or None,
        doc_id=parsed.doc_id,
        title=parsed.title,
        revision=parsed.revision,
        supplement=parsed.supplement,
        publisher=parsed.publisher,
        date_year=parsed.date_year,
        clause=parsed.clause,
        normalized_key=parsed.normalized_key,
        gaps=list(gaps or []),
    )


def extract_references_from_units(
    units: list[ExtractedUnit],
    extraction_issues: list[ExtractionIssue] | list[dict[str, Any]] | None = None,
) -> tuple[list[ExtractedRefCandidate], list[dict[str, Any]]]:
    """Return (candidates, gap_records)."""
    gaps: list[dict[str, Any]] = []
    for issue in extraction_issues or []:
        if hasattr(issue, "code"):
            gaps.append(
                {
                    "code": issue.code,
                    "message": issue.message,
                    "locator": getattr(issue, "locator", {}) or {},
                }
            )
        elif isinstance(issue, dict):
            gaps.append(
                {
                    "code": issue.get("code"),
                    "message": issue.get("message"),
                    "locator": issue.get("locator") or {},
                }
            )

    candidates: list[ExtractedRefCandidate] = []
    in_ref_section = False
    seen: set[tuple[str, str]] = set()

    for unit in units:
        text = (unit.text or "").strip()
        if not text:
            continue
        loc = unit.locator.to_dict()

        # Section enter/exit
        for line in text.splitlines():
            if _SECTION_HEADER_RE.match(line.strip()):
                in_ref_section = True
                break
        # Heuristic exit: new major numbered heading that isn't a ref header
        if in_ref_section and re.match(r"^\s*\d+\s+[A-Z].{3,}", text) and not _SECTION_HEADER_RE.match(
            text.splitlines()[0].strip() if text.splitlines() else ""
        ):
            # only exit if clearly a different chapter-like heading
            first = text.splitlines()[0].strip()
            if not _SECTION_HEADER_RE.match(first) and re.match(r"^\d+\s+", first):
                in_ref_section = False

        section_kind = _unit_section_kind(unit, in_ref_section)

        if section_kind == "references_section" or (
            in_ref_section and section_kind in {"table", "body"}
        ):
            for line in text.splitlines():
                line_s = _BULLET_RE.sub("", line).strip()
                if not line_s or _SECTION_HEADER_RE.match(line_s):
                    continue
                cand = _build_candidate(
                    line_s,
                    {**loc, "line": line_s[:120]},
                    "references_section" if in_ref_section else section_kind,
                    "section_line",
                    context=text[:400],
                    gaps=gaps if any(g.get("code") == "OCR_NEEDED" for g in gaps) else None,
                )
                if cand:
                    key = (cand.normalized_key, cand.section_kind)
                    if key not in seen:
                        seen.add(key)
                        candidates.append(cand)

        # Body / footnote / header / footer / table citations
        for cre in _CITATION_RES:
            for m in cre.finditer(text):
                raw = m.group(0)
                # Prefer fuller group when available
                if m.lastindex and m.lastindex >= 1 and m.group(1):
                    # Reconstruct with clause if present
                    parts = [m.group(1)]
                    if m.lastindex >= 2 and m.group(2):
                        parts.append(f"Rev {m.group(2)}")
                    if m.lastindex >= 3 and m.group(3):
                        parts.append(f"Clause {m.group(3)}")
                    raw = ", ".join(parts)
                cand = _build_candidate(
                    raw,
                    {**loc, "match_span": m.group(0)[:200]},
                    section_kind if section_kind != "references_section" else "body",
                    "citation_regex",
                    context=text[max(0, m.start() - 80) : m.end() + 80],
                )
                if cand:
                    key = (cand.normalized_key, str(loc))
                    if key not in seen:
                        seen.add(key)
                        candidates.append(cand)

    # If OCR gaps exist and we found nothing, surface an INSUFFICIENT_EVIDENCE gap
    if not candidates and any(g.get("code") in {"OCR_NEEDED", "UNREADABLE"} for g in gaps):
        gaps.append(
            {
                "code": "REFERENCE_EXTRACTION_BLOCKED",
                "message": "No references extracted; document has OCR/unreadable gaps",
                "locator": {},
            }
        )

    return candidates, gaps


def candidates_as_json(candidates: list[ExtractedRefCandidate]) -> list[dict[str, Any]]:
    return [c.to_persist_dict() for c in candidates]
