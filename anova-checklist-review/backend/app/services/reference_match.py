"""Auto-match extracted references against catalog / project sources / Qdrant.

Priority (auto-select only when id+version confident):
  1. id + revision
  2. id + supplement
  3. id + publisher + title
  4. semantic candidates only — NEVER auto-select by embedding alone

Unspecified revision: use project approved set as candidates, mark unspecified,
ask user if multiple — never silently pick latest.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.config import Settings
from app.core.enums import ReferenceStatus
from app.models.entities import (
    ExtractedReference,
    ProjectStandardSet,
    ReferenceMatch,
    StandardAlias,
    StandardCatalog,
    StandardVersion,
)
from app.services.normalize import normalize_doc_id, normalize_reference_key, normalize_revision


@dataclass
class CatalogCandidate:
    standard_id: uuid.UUID
    standard_version_id: uuid.UUID
    canonical_key: str
    title: str
    publisher: str | None
    version_label: str
    document_version_id: uuid.UUID | None
    match_method: str
    score: float
    meta: dict[str, Any] = field(default_factory=dict)


@dataclass
class MatchDecision:
    auto_selected: CatalogCandidate | None
    candidates: list[CatalogCandidate]
    resolution_state: str
    status_hint: str | None
    explanation: str


def _norm_title(t: str | None) -> str:
    return normalize_reference_key(t or "")


async def load_catalog_index(session: AsyncSession) -> list[dict[str, Any]]:
    rows = (
        await session.execute(
            select(StandardVersion, StandardCatalog)
            .join(StandardCatalog, StandardCatalog.id == StandardVersion.standard_id)
        )
    ).all()
    aliases = (
        await session.scalars(select(StandardAlias))
    ).all()
    alias_map: dict[uuid.UUID, list[str]] = {}
    for a in aliases:
        alias_map.setdefault(a.standard_id, []).append(a.alias_normalized)

    out = []
    for ver, cat in rows:
        out.append(
            {
                "standard_id": cat.id,
                "standard_version_id": ver.id,
                "canonical_key": cat.canonical_key,
                "canonical_key_norm": normalize_doc_id(cat.canonical_key),
                "title": cat.title,
                "title_norm": _norm_title(cat.title),
                "publisher": cat.publisher,
                "publisher_norm": (cat.publisher or "").strip().upper() or None,
                "version_label": ver.version_label,
                "version_norm": normalize_revision(ver.version_label),
                "supplement": (ver.meta or {}).get("supplement"),
                "supplement_norm": normalize_revision((ver.meta or {}).get("supplement")),
                "document_version_id": ver.document_version_id,
                "aliases": alias_map.get(cat.id, []),
            }
        )
    return out


async def load_project_approved_versions(
    session: AsyncSession, project_id: uuid.UUID
) -> set[uuid.UUID]:
    rows = (
        await session.scalars(
            select(ProjectStandardSet.standard_version_id).where(
                ProjectStandardSet.project_id == project_id
            )
        )
    ).all()
    return set(rows)


def _ids_match(ref_doc_id: str | None, entry: dict[str, Any]) -> bool:
    if not ref_doc_id:
        return False
    rid = normalize_doc_id(ref_doc_id)
    if rid == entry["canonical_key_norm"]:
        return True
    return any(rid == normalize_doc_id(a) or normalize_reference_key(rid) == a for a in entry["aliases"])


def match_reference(
    ref: ExtractedReference,
    catalog: list[dict[str, Any]],
    approved_version_ids: set[uuid.UUID],
    semantic_candidates: list[CatalogCandidate] | None = None,
) -> MatchDecision:
    """Deterministic match. semantic_candidates are advisory only."""
    doc_id = ref.doc_id_guess
    revision = normalize_revision(ref.version_guess)
    supplement = normalize_revision(ref.supplement_guess)
    publisher = (ref.publisher_guess or "").strip().upper() or None
    title_norm = _norm_title(ref.title_guess)

    by_id = [e for e in catalog if _ids_match(doc_id, e)]

    # --- Priority 1: id + revision ---
    if doc_id and revision:
        hits = [e for e in by_id if e["version_norm"] == revision]
        if len(hits) == 1:
            c = _to_candidate(hits[0], "id_revision", 1.0)
            return MatchDecision(
                auto_selected=c,
                candidates=[c],
                resolution_state="auto_selected",
                status_hint=None,
                explanation="Confident id+revision match",
            )
        if len(hits) > 1:
            cands = [_to_candidate(h, "id_revision", 0.95) for h in hits]
            return MatchDecision(
                None,
                cands,
                "needs_user",
                ReferenceStatus.AMBIGUOUS_MATCH,
                "Multiple catalog versions share id+revision",
            )

    # --- Priority 2: id + supplement ---
    if doc_id and supplement:
        hits = [e for e in by_id if e["supplement_norm"] == supplement]
        if len(hits) == 1:
            c = _to_candidate(hits[0], "id_supplement", 0.92)
            return MatchDecision(
                c, [c], "auto_selected", None, "Confident id+supplement match"
            )
        if len(hits) > 1:
            cands = [_to_candidate(h, "id_supplement", 0.9) for h in hits]
            return MatchDecision(
                None,
                cands,
                "needs_user",
                ReferenceStatus.AMBIGUOUS_MATCH,
                "Multiple catalog versions share id+supplement",
            )

    # --- Priority 3: id + publisher + title ---
    if doc_id and publisher and title_norm:
        hits = [
            e
            for e in by_id
            if e["publisher_norm"] == publisher
            and e["title_norm"]
            and (
                title_norm in e["title_norm"]
                or e["title_norm"] in title_norm
                or _token_overlap(title_norm, e["title_norm"]) >= 0.6
            )
        ]
        # Still need a single version — if multiple revisions, do not auto-pick latest
        if len(hits) == 1:
            c = _to_candidate(hits[0], "id_publisher_title", 0.85)
            return MatchDecision(
                c, [c], "auto_selected", None, "Confident id+publisher+title match"
            )
        if len(hits) > 1:
            cands = [_to_candidate(h, "id_publisher_title", 0.8) for h in hits]
            return MatchDecision(
                None,
                cands,
                "needs_user",
                ReferenceStatus.AMBIGUOUS_MATCH,
                "id+publisher+title matched multiple versions; user must choose",
            )

    # --- Unspecified revision with id known ---
    if doc_id and not revision:
        approved_hits = [e for e in by_id if e["standard_version_id"] in approved_version_ids]
        pool = approved_hits or by_id
        cands = [_to_candidate(h, "id_unspecified_revision", 0.7) for h in pool]
        if not cands:
            return MatchDecision(
                None,
                [],
                "missing_source",
                ReferenceStatus.MISSING_SOURCE,
                f"No catalog entry for id {doc_id}",
            )
        if len(cands) == 1:
            # Single approved/known version but revision unspecified in citation
            return MatchDecision(
                None,  # do NOT auto-select when revision unspecified
                cands,
                "needs_user",
                ReferenceStatus.VERSION_UNSPECIFIED,
                "Revision unspecified; single project-approved candidate — confirm with user",
            )
        return MatchDecision(
            None,
            cands,
            "needs_user",
            ReferenceStatus.VERSION_UNSPECIFIED,
            "Revision unspecified; multiple candidates from project approved set — ask user "
            "(never silently pick latest)",
        )

    # --- id only, no version path matched ---
    if doc_id and by_id:
        cands = [_to_candidate(h, "id_only", 0.55) for h in by_id]
        return MatchDecision(
            None,
            cands,
            "needs_user",
            ReferenceStatus.AMBIGUOUS_MATCH,
            "Document id matched catalog but version not confident enough to auto-select",
        )

    # --- Semantic candidates only (never auto) ---
    sem = list(semantic_candidates or [])
    if sem:
        return MatchDecision(
            None,
            sem,
            "needs_user",
            ReferenceStatus.AMBIGUOUS_MATCH,
            "Semantic candidates only — embedding alone never auto-selects",
        )

    return MatchDecision(
        None,
        [],
        "missing_source",
        ReferenceStatus.MISSING_SOURCE,
        "No catalog/source match for reference",
    )


def _token_overlap(a: str, b: str) -> float:
    ta, tb = set(a.split()), set(b.split())
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / float(len(ta | tb))


def _to_candidate(entry: dict[str, Any], method: str, score: float) -> CatalogCandidate:
    return CatalogCandidate(
        standard_id=entry["standard_id"],
        standard_version_id=entry["standard_version_id"],
        canonical_key=entry["canonical_key"],
        title=entry["title"],
        publisher=entry["publisher"],
        version_label=entry["version_label"],
        document_version_id=entry["document_version_id"],
        match_method=method,
        score=score,
        meta={"supplement": entry.get("supplement")},
    )


async def fetch_semantic_candidates(
    settings: Settings,
    ref: ExtractedReference,
    catalog: list[dict[str, Any]],
    limit: int = 5,
) -> list[CatalogCandidate]:
    """Optional Qdrant lookup — advisory only. Failures yield empty list."""
    if not ref.raw_text:
        return []
    try:
        from qdrant_client import QdrantClient
        from qdrant_client.http import models as qm

        from app.services.embedding_client import EmbeddingClient
        from app.services.qdrant_index import DENSE_VECTOR_NAME

        async with EmbeddingClient(settings) as emb:
            vectors = await emb.embed([ref.raw_text[:1500]])
        if not vectors:
            return []
        client = QdrantClient(url=settings.qdrant_url, prefer_grpc=False)
        hits = client.search(
            collection_name=settings.qdrant_collection_standards,
            query_vector=(DENSE_VECTOR_NAME, vectors[0].dense),
            limit=limit,
            with_payload=True,
        )
        by_sv = {e["standard_version_id"]: e for e in catalog}
        out: list[CatalogCandidate] = []
        seen: set[uuid.UUID] = set()
        for h in hits:
            payload = h.payload or {}
            sv_raw = payload.get("standard_version_id")
            if not sv_raw:
                continue
            sv_id = uuid.UUID(str(sv_raw))
            if sv_id in seen:
                continue
            seen.add(sv_id)
            entry = by_sv.get(sv_id)
            if not entry:
                continue
            out.append(
                _to_candidate(entry, "semantic_candidate", float(h.score or 0.0))
            )
        return out
    except Exception:  # noqa: BLE001
        return []


async def persist_match_decision(
    session: AsyncSession,
    ref: ExtractedReference,
    decision: MatchDecision,
) -> list[ReferenceMatch]:
    # Clear prior matches for re-resolution
    existing = (
        await session.scalars(
            select(ReferenceMatch).where(ReferenceMatch.extracted_reference_id == ref.id)
        )
    ).all()
    for row in existing:
        await session.delete(row)
    await session.flush()

    created: list[ReferenceMatch] = []
    for rank, cand in enumerate(decision.candidates):
        m = ReferenceMatch(
            id=uuid.uuid4(),
            extracted_reference_id=ref.id,
            standard_version_id=cand.standard_version_id,
            document_version_id=cand.document_version_id,
            score=cand.score,
            rank=rank,
            match_method=cand.match_method,
            meta={
                "canonical_key": cand.canonical_key,
                "title": cand.title,
                "publisher": cand.publisher,
                "version_label": cand.version_label,
                **cand.meta,
            },
        )
        session.add(m)
        created.append(m)
    await session.flush()

    ref.resolution_state = decision.resolution_state
    if decision.auto_selected and created:
        ref.selected_match_id = created[0].id
    elif decision.resolution_state == "missing_source":
        ref.selected_match_id = None
    return created
