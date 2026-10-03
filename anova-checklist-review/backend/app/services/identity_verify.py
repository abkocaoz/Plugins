"""Verify uploaded missing-source identity from content, not filename."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from app.services.extraction import extract_document
from app.services.normalize import normalize_doc_id, parse_reference


@dataclass
class IdentityVerdict:
    ok: bool
    expected_doc_id: str | None
    found_doc_ids: list[str]
    found_titles: list[str]
    explanation: str
    content_sha_preview: str | None = None


def verify_upload_identity(
    data: bytes,
    filename: str,
    mime_type: str | None,
    *,
    expected_doc_id: str | None,
    expected_title_substr: str | None = None,
) -> IdentityVerdict:
    result = extract_document(data, filename, mime_type)
    # Use head of document only for identity
    head = result.full_text[:4000]
    found_ids: list[str] = []
    found_titles: list[str] = []
    for unit in result.units[:40]:
        parsed = parse_reference(unit.text)
        if parsed.doc_id and parsed.doc_id not in found_ids:
            found_ids.append(parsed.doc_id)
        if parsed.title and parsed.title not in found_titles:
            found_titles.append(parsed.title)
    # Also parse whole head once
    head_parsed = parse_reference(head)
    if head_parsed.doc_id and head_parsed.doc_id not in found_ids:
        found_ids.insert(0, head_parsed.doc_id)

    if not expected_doc_id:
        return IdentityVerdict(
            ok=bool(found_ids) or bool(head.strip()),
            expected_doc_id=None,
            found_doc_ids=found_ids,
            found_titles=found_titles,
            explanation="No expected id provided; recorded ids found in content",
        )

    exp = normalize_doc_id(expected_doc_id)
    if any(normalize_doc_id(i) == exp for i in found_ids):
        return IdentityVerdict(
            True,
            exp,
            found_ids,
            found_titles,
            "Expected document id found in content (filename ignored)",
        )

    if expected_title_substr and expected_title_substr.lower() in head.lower():
        return IdentityVerdict(
            True,
            exp,
            found_ids,
            found_titles,
            "Expected title substring found in content; id not present in head",
        )

    return IdentityVerdict(
        False,
        exp,
        found_ids,
        found_titles,
        (
            f"Content does not confirm expected id {exp}. "
            f"Found ids={found_ids or '[]'}. Filename '{Path(filename).name}' is not used as proof."
        ),
    )
