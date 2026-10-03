"""Reference validation checks with distinct statuses and findings.

Checks: bibliographic, in-doc consistency, clause presence, project applicability.
Suggested fixes never mutate the source document.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import ReferenceStatus
from app.models.entities import (
    ExtractedReference,
    ProjectStandardSet,
    ReferenceFinding,
    ReferenceMatch,
    StandardCatalog,
    StandardVersion,
)
from app.services.normalize import normalize_doc_id, normalize_revision


@dataclass
class FindingDraft:
    status: str
    check_type: str
    message: str
    details: dict[str, Any] = field(default_factory=dict)
    blocks_dependent_items: bool = False
    reference_match_id: uuid.UUID | None = None


def _suggested_fix(kind: str, **kwargs: Any) -> dict[str, Any]:
    """Human-facing suggestion only — never applied to the document automatically."""
    return {"kind": kind, "auto_apply": False, **kwargs}


async def validate_reference(
    session: AsyncSession,
    ref: ExtractedReference,
    *,
    project_id: uuid.UUID,
    sibling_refs: list[ExtractedReference],
    source_text: str | None,
) -> list[FindingDraft]:
    findings: list[FindingDraft] = []

    selected: ReferenceMatch | None = None
    if ref.selected_match_id:
        selected = await session.get(ReferenceMatch, ref.selected_match_id)

    matches = (
        await session.scalars(
            select(ReferenceMatch)
            .where(ReferenceMatch.extracted_reference_id == ref.id)
            .order_by(ReferenceMatch.rank.asc())
        )
    ).all()

    # --- Missing / ambiguous resolution ---
    if ref.resolution_state == "missing_source" or (
        not selected and not matches and ref.resolution_state != "needs_user"
    ):
        findings.append(
            FindingDraft(
                status=ReferenceStatus.MISSING_SOURCE,
                check_type="bibliographic",
                message=f"Missing source for reference '{ref.raw_text[:160]}'",
                details={
                    "searched_id": ref.doc_id_guess,
                    "searched_revision": ref.version_guess,
                    "searched_supplement": ref.supplement_guess,
                    "locations": [ref.locator],
                    "alternate_versions_found": [],
                    "suggested_fix": _suggested_fix(
                        "upload_missing_source",
                        searched_id=ref.doc_id_guess,
                        searched_revision=ref.version_guess,
                    ),
                },
                blocks_dependent_items=True,
            )
        )
        return findings

    if ref.resolution_state == "needs_user":
        alt = [
            {
                "standard_version_id": str(m.standard_version_id),
                "version_label": (m.meta or {}).get("version_label"),
                "canonical_key": (m.meta or {}).get("canonical_key"),
                "match_method": m.match_method,
                "score": m.score,
            }
            for m in matches
        ]
        status = ReferenceStatus.VERSION_UNSPECIFIED
        if any(m.match_method == "semantic_candidate" for m in matches) and not ref.version_guess:
            status = ReferenceStatus.VERSION_UNSPECIFIED
        if ref.version_guess and len(matches) > 1:
            status = ReferenceStatus.AMBIGUOUS_MATCH
        if not ref.version_guess:
            status = ReferenceStatus.VERSION_UNSPECIFIED
        findings.append(
            FindingDraft(
                status=status,
                check_type="bibliographic",
                message="User selection required before reference can be verified",
                details={
                    "searched_id": ref.doc_id_guess,
                    "searched_revision": ref.version_guess,
                    "locations": [ref.locator],
                    "alternate_versions_found": alt,
                    "suggested_fix": _suggested_fix(
                        "select_candidate_version",
                        candidates=alt,
                        note="Do not silently pick latest",
                    ),
                },
                blocks_dependent_items=True,
                reference_match_id=matches[0].id if matches else None,
            )
        )
        # Still run consistency among siblings
        findings.extend(_consistency_findings(ref, sibling_refs))
        return findings

    # Selected match path
    assert selected is not None or matches
    sel = selected or matches[0]
    std_ver = (
        await session.get(StandardVersion, sel.standard_version_id)
        if sel.standard_version_id
        else None
    )
    std = (
        await session.get(StandardCatalog, std_ver.standard_id) if std_ver else None
    )

    # Bibliographic
    findings.extend(
        _bibliographic_findings(ref, sel, std, std_ver)
    )

    # In-document consistency
    findings.extend(_consistency_findings(ref, sibling_refs))

    # Clause check
    findings.extend(
        await _clause_findings(session, ref, sel, std_ver, source_text)
    )

    # Project applicability
    findings.extend(
        await _applicability_findings(session, project_id, ref, sel, std_ver)
    )

    # If no negative findings, emit VERIFIED bibliographic pass summary
    negative = {
        ReferenceStatus.METADATA_MISMATCH,
        ReferenceStatus.VERSION_MISMATCH,
        ReferenceStatus.VERSION_UNSPECIFIED,
        ReferenceStatus.CLAUSE_NOT_FOUND,
        ReferenceStatus.CLAIM_NOT_SUPPORTED,
        ReferenceStatus.MISSING_SOURCE,
        ReferenceStatus.AMBIGUOUS_MATCH,
        ReferenceStatus.INSUFFICIENT_EVIDENCE,
        ReferenceStatus.MANUAL_REVIEW,
    }
    if not any(f.status in negative for f in findings):
        findings.insert(
            0,
            FindingDraft(
                status=ReferenceStatus.VERIFIED,
                check_type="bibliographic",
                message="Reference verified against selected catalog version",
                details={
                    "location": ref.locator,
                    "selected_source": {
                        "standard_version_id": str(sel.standard_version_id),
                        "canonical_key": (sel.meta or {}).get("canonical_key"),
                        "version_label": (sel.meta or {}).get("version_label"),
                    },
                    "clause": ref.clause_guess,
                    "quote": None,
                    "explanation": "id/version metadata align; no blocking findings",
                    "suggested_fix": None,
                },
                reference_match_id=sel.id,
            ),
        )
    return findings


def _bibliographic_findings(
    ref: ExtractedReference,
    sel: ReferenceMatch,
    std: StandardCatalog | None,
    std_ver: StandardVersion | None,
) -> list[FindingDraft]:
    out: list[FindingDraft] = []
    if not std or not std_ver:
        out.append(
            FindingDraft(
                status=ReferenceStatus.INSUFFICIENT_EVIDENCE,
                check_type="bibliographic",
                message="Selected match lacks catalog metadata",
                details={
                    "location": ref.locator,
                    "suggested_fix": _suggested_fix("relink_catalog_entry"),
                },
                reference_match_id=sel.id,
                blocks_dependent_items=True,
            )
        )
        return out

    if ref.doc_id_guess and normalize_doc_id(ref.doc_id_guess) != normalize_doc_id(
        std.canonical_key
    ):
        # aliases may still be ok — only flag hard mismatch when clearly different family
        if normalize_doc_id(ref.doc_id_guess) not in normalize_doc_id(std.canonical_key):
            out.append(
                FindingDraft(
                    status=ReferenceStatus.METADATA_MISMATCH,
                    check_type="bibliographic",
                    message="Cited document id does not match selected catalog canonical key",
                    details={
                        "location": ref.locator,
                        "selected_source": {
                            "canonical_key": std.canonical_key,
                            "version_label": std_ver.version_label,
                        },
                        "explanation": f"cited={ref.doc_id_guess} selected={std.canonical_key}",
                        "suggested_fix": _suggested_fix(
                            "correct_citation_or_selection",
                            cited_id=ref.doc_id_guess,
                            catalog_key=std.canonical_key,
                        ),
                    },
                    reference_match_id=sel.id,
                )
            )

    if ref.version_guess and normalize_revision(ref.version_guess) != normalize_revision(
        std_ver.version_label
    ):
        out.append(
            FindingDraft(
                status=ReferenceStatus.VERSION_MISMATCH,
                check_type="bibliographic",
                message="Cited revision differs from selected catalog version",
                details={
                    "location": ref.locator,
                    "selected_source": {
                        "standard_version_id": str(std_ver.id),
                        "version_label": std_ver.version_label,
                    },
                    "explanation": f"cited_rev={ref.version_guess} selected_rev={std_ver.version_label}",
                    "suggested_fix": _suggested_fix(
                        "align_revision",
                        cited_revision=ref.version_guess,
                        catalog_revision=std_ver.version_label,
                        note="Suggestion only — document is not mutated",
                    ),
                },
                reference_match_id=sel.id,
                blocks_dependent_items=True,
            )
        )

    if ref.title_guess and std.title:
        # soft metadata mismatch
        cited = ref.title_guess.lower()
        cat = std.title.lower()
        if cited not in cat and cat not in cited and len(set(cited.split()) & set(cat.split())) < 2:
            out.append(
                FindingDraft(
                    status=ReferenceStatus.METADATA_MISMATCH,
                    check_type="bibliographic",
                    message="Cited title poorly matches catalog title",
                    details={
                        "location": ref.locator,
                        "selected_source": {"title": std.title},
                        "explanation": f"cited_title={ref.title_guess!r}",
                        "suggested_fix": _suggested_fix(
                            "review_title", catalog_title=std.title
                        ),
                    },
                    reference_match_id=sel.id,
                )
            )
    return out


def _consistency_findings(
    ref: ExtractedReference, siblings: list[ExtractedReference]
) -> list[FindingDraft]:
    out: list[FindingDraft] = []
    if not ref.doc_id_guess:
        return out
    same_id = [
        s
        for s in siblings
        if s.id != ref.id
        and s.doc_id_guess
        and normalize_doc_id(s.doc_id_guess) == normalize_doc_id(ref.doc_id_guess)
    ]
    revs = {(normalize_revision(ref.version_guess) or "")}
    for s in same_id:
        revs.add(normalize_revision(s.version_guess) or "")
    # empty string means unspecified — conflict if both specified and differ
    specified = {r for r in revs if r}
    if len(specified) > 1:
        out.append(
            FindingDraft(
                status=ReferenceStatus.VERSION_MISMATCH,
                check_type="consistency",
                message="Same document id cited with conflicting revisions in this document",
                details={
                    "location": ref.locator,
                    "explanation": f"revisions_seen={sorted(specified)}",
                    "sibling_locations": [s.locator for s in same_id],
                    "suggested_fix": _suggested_fix(
                        "harmonize_in_document_revisions",
                        revisions=sorted(specified),
                        note="Suggestion only — document is not mutated",
                    ),
                },
            )
        )
    return out


async def _clause_findings(
    session: AsyncSession,
    ref: ExtractedReference,
    sel: ReferenceMatch,
    std_ver: StandardVersion | None,
    source_text: str | None,
) -> list[FindingDraft]:
    if not ref.clause_guess:
        return []
    # Prefer indexed source document text when linked
    text = source_text or ""
    if std_ver and std_ver.document_version_id:
        from app.models.entities import DocumentVersion

        dv = await session.get(DocumentVersion, std_ver.document_version_id)
        if dv and dv.extracted_text_path:
            from pathlib import Path

            p = Path(dv.extracted_text_path)
            if p.is_file():
                text = p.read_text(encoding="utf-8", errors="replace")

    if not text.strip():
        return [
            FindingDraft(
                status=ReferenceStatus.INSUFFICIENT_EVIDENCE,
                check_type="clause",
                message=f"Cannot verify clause {ref.clause_guess}: source text unavailable",
                details={
                    "location": ref.locator,
                    "clause": ref.clause_guess,
                    "selected_source": {
                        "standard_version_id": str(sel.standard_version_id)
                        if sel.standard_version_id
                        else None
                    },
                    "suggested_fix": _suggested_fix(
                        "upload_or_index_source_for_clause_check"
                    ),
                },
                reference_match_id=sel.id,
                blocks_dependent_items=True,
            )
        ]

    clause = ref.clause_guess
    # Look for clause markers in source
    patterns = [clause, f"Clause {clause}", f"Section {clause}", f"§{clause}"]
    found = any(p.lower() in text.lower() for p in patterns)
    if found:
        # grab a short quote
        idx = text.lower().find(clause.lower())
        quote = text[max(0, idx - 40) : idx + 80].replace("\n", " ").strip() if idx >= 0 else None
        return [
            FindingDraft(
                status=ReferenceStatus.VERIFIED,
                check_type="clause",
                message=f"Clause {clause} found in selected source",
                details={
                    "location": ref.locator,
                    "clause": clause,
                    "quote": quote,
                    "selected_source": {
                        "standard_version_id": str(sel.standard_version_id)
                        if sel.standard_version_id
                        else None
                    },
                    "suggested_fix": None,
                },
                reference_match_id=sel.id,
            )
        ]
    return [
        FindingDraft(
            status=ReferenceStatus.CLAUSE_NOT_FOUND,
            check_type="clause",
            message=f"Clause {clause} not found in selected source text",
            details={
                "location": ref.locator,
                "clause": clause,
                "quote": None,
                "selected_source": {
                    "standard_version_id": str(sel.standard_version_id)
                    if sel.standard_version_id
                    else None
                },
                "explanation": "Clause marker absent from extracted source text",
                "suggested_fix": _suggested_fix(
                    "verify_clause_number_or_source_version",
                    clause=clause,
                    note="Suggestion only — document is not mutated",
                ),
            },
            reference_match_id=sel.id,
            blocks_dependent_items=True,
        )
    ]


async def _applicability_findings(
    session: AsyncSession,
    project_id: uuid.UUID,
    ref: ExtractedReference,
    sel: ReferenceMatch,
    std_ver: StandardVersion | None,
) -> list[FindingDraft]:
    if not sel.standard_version_id:
        return []
    approved = (
        await session.scalars(
            select(ProjectStandardSet).where(
                ProjectStandardSet.project_id == project_id,
                ProjectStandardSet.standard_version_id == sel.standard_version_id,
            )
        )
    ).first()
    if approved:
        return [
            FindingDraft(
                status=ReferenceStatus.VERIFIED,
                check_type="applicability",
                message="Selected version is in the project approved standard set",
                details={
                    "location": ref.locator,
                    "selected_source": {
                        "standard_version_id": str(sel.standard_version_id),
                        "version_label": std_ver.version_label if std_ver else None,
                    },
                    "suggested_fix": None,
                },
                reference_match_id=sel.id,
            )
        ]
    # Not in approved set — manual review, does not hard-block independent checklist items
    return [
        FindingDraft(
            status=ReferenceStatus.MANUAL_REVIEW,
            check_type="applicability",
            message="Selected version is not in the project approved standard set",
            details={
                "location": ref.locator,
                "selected_source": {
                    "standard_version_id": str(sel.standard_version_id),
                    "version_label": std_ver.version_label if std_ver else None,
                },
                "explanation": "Add to project standard set or choose an approved version",
                "suggested_fix": _suggested_fix(
                    "add_to_project_standard_set_or_reselect",
                    standard_version_id=str(sel.standard_version_id),
                ),
            },
            reference_match_id=sel.id,
            blocks_dependent_items=False,
        )
    ]


async def persist_findings(
    session: AsyncSession,
    ref: ExtractedReference,
    drafts: list[FindingDraft],
    *,
    replace: bool = True,
) -> list[ReferenceFinding]:
    if replace:
        old = (
            await session.scalars(
                select(ReferenceFinding).where(
                    ReferenceFinding.extracted_reference_id == ref.id
                )
            )
        ).all()
        for row in old:
            await session.delete(row)
        await session.flush()

    created: list[ReferenceFinding] = []
    for d in drafts:
        row = ReferenceFinding(
            id=uuid.uuid4(),
            extracted_reference_id=ref.id,
            reference_match_id=d.reference_match_id,
            status=d.status,
            check_type=d.check_type,
            message=d.message,
            details=d.details,
            blocks_dependent_items=d.blocks_dependent_items,
        )
        session.add(row)
        created.append(row)
    await session.flush()
    return created
