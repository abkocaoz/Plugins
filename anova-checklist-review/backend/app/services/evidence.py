"""Evidence packs for checklist evaluation (IDs cited by LLM must exist here)."""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass, field
from typing import Any


@dataclass
class EvidenceItem:
    evidence_id: str
    document_version_id: uuid.UUID
    project_id: uuid.UUID
    quote: str
    locator: dict[str, Any]
    content_sha256: str | None = None
    revision: str | None = None
    kind: str = "document_unit"

    def to_prompt_dict(self) -> dict[str, Any]:
        return {
            "evidence_id": self.evidence_id,
            "document_version_id": str(self.document_version_id),
            "revision": self.revision,
            "locator": self.locator,
            "quote": self.quote[:1200],
        }


@dataclass
class EvidencePack:
    project_id: uuid.UUID
    document_version_id: uuid.UUID
    version_label: str
    content_sha256: str
    items: list[EvidenceItem] = field(default_factory=list)
    # Phase 6: cross-document packs
    pinned_document_version_ids: list[uuid.UUID] = field(default_factory=list)
    items_by_version: dict[str, list[EvidenceItem]] = field(default_factory=dict)
    doc_types_by_version: dict[str, str] = field(default_factory=dict)

    def by_id(self) -> dict[str, EvidenceItem]:
        return {e.evidence_id: e for e in self.items}

    def to_prompt_list(self) -> list[dict[str, Any]]:
        return [e.to_prompt_dict() for e in self.items]

    def allowed_document_version_ids(self) -> set[uuid.UUID]:
        allowed = {self.document_version_id}
        allowed.update(self.pinned_document_version_ids or [])
        return allowed


def make_evidence_id(document_version_id: uuid.UUID, locator: dict[str, Any], quote: str) -> str:
    raw = f"{document_version_id}|{sorted(locator.items())}|{quote[:200]}".encode()
    return "ev_" + hashlib.sha1(raw).hexdigest()[:16]


def build_evidence_pack_from_units(
    *,
    project_id: uuid.UUID,
    document_version_id: uuid.UUID,
    version_label: str,
    content_sha256: str,
    units: list[Any],
    doc_type: str | None = None,
    pinned_document_version_ids: list[uuid.UUID] | None = None,
) -> EvidencePack:
    pack = EvidencePack(
        project_id=project_id,
        document_version_id=document_version_id,
        version_label=version_label,
        content_sha256=content_sha256,
        pinned_document_version_ids=list(pinned_document_version_ids or []),
    )
    _append_units_to_pack(
        pack,
        document_version_id=document_version_id,
        version_label=version_label,
        content_sha256=content_sha256,
        units=units,
        doc_type=doc_type,
    )
    return pack


def _append_units_to_pack(
    pack: EvidencePack,
    *,
    document_version_id: uuid.UUID,
    version_label: str,
    content_sha256: str,
    units: list[Any],
    doc_type: str | None = None,
) -> None:
    key = str(document_version_id)
    bucket = pack.items_by_version.setdefault(key, [])
    if doc_type:
        pack.doc_types_by_version[key] = doc_type
    for unit in units:
        text = (getattr(unit, "text", None) or "").strip()
        if not text:
            continue
        locator = unit.locator.to_dict() if hasattr(unit.locator, "to_dict") else dict(unit.locator)
        locator = dict(locator)
        if doc_type:
            locator["doc_type"] = doc_type
            extra = dict(locator.get("extra") or {})
            extra["doc_type"] = doc_type
            locator["extra"] = extra
        eid = make_evidence_id(document_version_id, locator, text)
        item = EvidenceItem(
            evidence_id=eid,
            document_version_id=document_version_id,
            project_id=pack.project_id,
            quote=text,
            locator=locator,
            content_sha256=content_sha256,
            revision=version_label,
        )
        pack.items.append(item)
        bucket.append(item)


def merge_evidence_packs(
    primary: EvidencePack,
    peers: list[tuple[EvidencePack, str | None]],
) -> EvidencePack:
    """Merge peer packs into primary for cross-document evaluation."""
    merged = EvidencePack(
        project_id=primary.project_id,
        document_version_id=primary.document_version_id,
        version_label=primary.version_label,
        content_sha256=primary.content_sha256,
        items=list(primary.items),
        pinned_document_version_ids=list(primary.pinned_document_version_ids),
        items_by_version={k: list(v) for k, v in (primary.items_by_version or {}).items()},
        doc_types_by_version=dict(primary.doc_types_by_version or {}),
    )
    if str(primary.document_version_id) not in merged.items_by_version:
        merged.items_by_version[str(primary.document_version_id)] = list(primary.items)
    for peer, doc_type in peers:
        vid = peer.document_version_id
        if vid not in merged.pinned_document_version_ids and vid != primary.document_version_id:
            merged.pinned_document_version_ids.append(vid)
        if doc_type:
            merged.doc_types_by_version[str(vid)] = doc_type
        elif peer.doc_types_by_version.get(str(vid)):
            merged.doc_types_by_version[str(vid)] = peer.doc_types_by_version[str(vid)]
        bucket = merged.items_by_version.setdefault(str(vid), [])
        for item in peer.items:
            # Retag locator doc_type if provided
            if doc_type and not (item.locator or {}).get("doc_type"):
                loc = dict(item.locator or {})
                loc["doc_type"] = doc_type
                item = EvidenceItem(
                    evidence_id=item.evidence_id,
                    document_version_id=item.document_version_id,
                    project_id=item.project_id,
                    quote=item.quote,
                    locator=loc,
                    content_sha256=item.content_sha256,
                    revision=item.revision,
                    kind=item.kind,
                )
            merged.items.append(item)
            bucket.append(item)
    return merged


def filter_evidence(
    pack: EvidencePack, terms: list[str], *, limit: int | None = None, full_scan: bool = False
) -> list[EvidenceItem]:
    if full_scan or not terms:
        items = list(pack.items)
    else:
        lowered = [t.lower() for t in terms]
        items = [e for e in pack.items if any(t in e.quote.lower() for t in lowered)]
        # If query terms miss everything, return empty — caller must not invent NO
        if not items:
            return []
    if limit is not None and not full_scan:
        items = items[:limit]
    return items
