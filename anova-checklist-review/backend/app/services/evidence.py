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

    def by_id(self) -> dict[str, EvidenceItem]:
        return {e.evidence_id: e for e in self.items}

    def to_prompt_list(self) -> list[dict[str, Any]]:
        return [e.to_prompt_dict() for e in self.items]


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
) -> EvidencePack:
    pack = EvidencePack(
        project_id=project_id,
        document_version_id=document_version_id,
        version_label=version_label,
        content_sha256=content_sha256,
    )
    for unit in units:
        text = (getattr(unit, "text", None) or "").strip()
        if not text:
            continue
        locator = unit.locator.to_dict() if hasattr(unit.locator, "to_dict") else dict(unit.locator)
        eid = make_evidence_id(document_version_id, locator, text)
        pack.items.append(
            EvidenceItem(
                evidence_id=eid,
                document_version_id=document_version_id,
                project_id=project_id,
                quote=text,
                locator=locator,
                content_sha256=content_sha256,
                revision=version_label,
            )
        )
    return pack


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
