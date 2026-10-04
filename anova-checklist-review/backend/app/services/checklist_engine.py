"""Checklist evaluation engine (Phases 4–6: SCS, DataICD, SECI)."""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from app.core.config import Settings
from app.core.enums import ChecklistAnswerState, ChecklistMethod, ReferenceStatus
from app.models.entities import (
    ChecklistAnswer,
    ChecklistDefinition,
    ChecklistItem,
    ChecklistRun,
    Document,
    DocumentVersion,
    EvidenceLink,
    ExtractedReference,
    ProjectStandardSet,
    ReferenceFinding,
    Review,
)
from app.services.checklist_rules import (
    RuleResult,
    run_deterministic_rule,
    run_traceability_full_scan,
)
from app.services.evidence import (
    EvidenceItem,
    EvidencePack,
    build_evidence_pack_from_units,
    filter_evidence,
    merge_evidence_packs,
)
from app.services.ollama_checklist import ollama_checklist_evaluate

logger = logging.getLogger(__name__)


def _load_units_for_version(version: DocumentVersion) -> list[Any]:
    import json

    from app.services.extraction import ExtractedUnit, Locator

    meta = version.meta or {}
    extraction = meta.get("extraction") or {}
    json_path = extraction.get("extraction_json_path")
    if not json_path or not Path(json_path).is_file():
        # Fallback: treat full_text as one unit if present
        if version.extracted_text_path and Path(version.extracted_text_path).is_file():
            text = Path(version.extracted_text_path).read_text(encoding="utf-8", errors="replace")
            return [
                ExtractedUnit(
                    text=text, locator=Locator(kind="full_text", extra={"fallback": True})
                )
            ]
        return []
    data = json.loads(Path(json_path).read_text(encoding="utf-8"))
    units = []
    for u in data.get("units") or []:
        loc_raw = u.get("locator") or {}
        units.append(
            ExtractedUnit(
                text=u.get("text") or "",
                locator=Locator(
                    kind=loc_raw.get("kind") or "unknown",
                    page=loc_raw.get("page"),
                    paragraph=loc_raw.get("paragraph"),
                    sheet=loc_raw.get("sheet"),
                    row=loc_raw.get("row"),
                    column=loc_raw.get("column"),
                    line_start=loc_raw.get("line_start"),
                    line_end=loc_raw.get("line_end"),
                    extra=loc_raw.get("extra") or {},
                ),
            )
        )
    return units


def verify_evidence_citations(
    *,
    proposed_ids: list[str],
    pack: EvidencePack,
    require_quote: bool = True,
) -> tuple[list[str], list[str]]:
    """Server-side verify evidence IDs, project/revision, quote presence.

    Returns (valid_ids, invalid_ids).
    """
    by_id = pack.by_id()
    valid: list[str] = []
    invalid: list[str] = []
    for eid in proposed_ids:
        item = by_id.get(eid)
        if item is None:
            invalid.append(eid)
            continue
        if item.project_id != pack.project_id:
            invalid.append(eid)
            continue
        allowed = pack.allowed_document_version_ids()
        if item.document_version_id not in allowed:
            invalid.append(eid)
            continue
        # Revision check only for primary-pack items when single-doc; multi-doc allows peer revisions
        if (
            len(allowed) <= 1
            and item.revision
            and item.revision != pack.version_label
        ):
            invalid.append(eid)
            continue
        if require_quote and not (item.quote or "").strip():
            invalid.append(eid)
            continue
        valid.append(eid)
    return valid, invalid


def enforce_answer_semantics(
    state: str,
    *,
    subchecks: list[dict[str, Any]],
    inapplicability_rationale: str | None,
    valid_evidence_ids: list[str],
    invalid_evidence_ids: list[str],
    confidence: float | None,
) -> tuple[str, str]:
    """Post-conditions. Model confidence is never auto-approve."""
    notes = []
    if invalid_evidence_ids:
        return (
            ChecklistAnswerState.ERROR,
            f"Fake/unknown evidence IDs rejected: {invalid_evidence_ids}",
        )
    if state == ChecklistAnswerState.NA:
        if not (inapplicability_rationale or "").strip():
            return (
                ChecklistAnswerState.INSUFFICIENT_EVIDENCE,
                "NA rejected: inapplicability rationale required (missing evidence ≠ NA)",
            )
    if state == ChecklistAnswerState.YES:
        if subchecks and not all(bool(s.get("passed")) for s in subchecks):
            return (
                ChecklistAnswerState.NO,
                "YES rejected: not all subchecks passed",
            )
        if not valid_evidence_ids:
            return (
                ChecklistAnswerState.INSUFFICIENT_EVIDENCE,
                "YES rejected: no verified evidence IDs (confidence ignored)",
            )
    if confidence is not None:
        notes.append(f"model_confidence={confidence} (not used for approval)")
    return state, "; ".join(notes) if notes else ""


async def _reference_dependency_blockers(
    session: AsyncSession,
    document_version_id: uuid.UUID,
    dep_ids: list[str],
) -> list[dict[str, Any]]:
    if not dep_ids:
        return []
    refs = (
        await session.scalars(
            select(ExtractedReference).where(
                ExtractedReference.document_version_id == document_version_id
            )
        )
    ).all()
    blockers: list[dict[str, Any]] = []
    for dep in dep_ids:
        dep_u = dep.upper().replace(" ", "-")
        matched_refs = [
            r
            for r in refs
            if r.doc_id_guess and dep_u in r.doc_id_guess.upper().replace(" ", "-")
        ]
        if not matched_refs:
            blockers.append(
                {
                    "dependency": dep,
                    "status": ReferenceStatus.MISSING_SOURCE,
                    "message": f"Required reference {dep} not extracted/matched",
                }
            )
            continue
        for ref in matched_refs:
            findings = (
                await session.scalars(
                    select(ReferenceFinding).where(
                        ReferenceFinding.extracted_reference_id == ref.id
                    )
                )
            ).all()
            critical = [
                f
                for f in findings
                if f.status
                in {
                    ReferenceStatus.MISSING_SOURCE,
                    ReferenceStatus.AMBIGUOUS_MATCH,
                    ReferenceStatus.VERSION_UNSPECIFIED,
                    ReferenceStatus.VERSION_MISMATCH,
                }
                or f.blocks_dependent_items
            ]
            if ref.resolution_state in {"missing_source", "needs_user"} or critical:
                blockers.append(
                    {
                        "dependency": dep,
                        "extracted_reference_id": str(ref.id),
                        "resolution_state": ref.resolution_state,
                        "statuses": [f.status for f in critical] or [ref.resolution_state],
                        "message": critical[0].message
                        if critical
                        else f"Reference {dep} not confidently resolved",
                    }
                )
    return blockers


async def evaluate_item(
    session: AsyncSession,
    settings: Settings,
    *,
    run: ChecklistRun,
    item: ChecklistItem,
    pack: EvidencePack,
    applicability_yes: bool | None = None,
) -> ChecklistAnswer:
    schema = item.schema_json or {}
    method = item.method
    cells = schema.get("excel_cells") or {}
    subchecks_def = schema.get("subchecks") or []
    deps = schema.get("reference_dependencies") or []
    full_scan = bool(schema.get("requires_full_scan"))
    method_config = schema.get("method_config") or {}

    ai_proposal: dict[str, Any] = {
        "method": method,
        "engine": "phase6",
    }
    state = ChecklistAnswerState.PENDING
    rationale = ""
    chapter = None
    comment = None
    confidence = None
    evidence_ids: list[str] = []
    subcheck_results: list[dict[str, Any]] = []
    # Applicability display value for Is Applicable column (never store conformity here)
    is_applicable_value: str | None = None

    primary_doc_type = (pack.doc_types_by_version or {}).get(str(pack.document_version_id))
    pinned_doc_types = [
        (pack.doc_types_by_version or {}).get(str(vid), "")
        for vid in (pack.pinned_document_version_ids or [])
    ]

    # Dependent items blocked by missing/critical references
    if item.depends_on_references or deps:
        blockers = await _reference_dependency_blockers(
            session, run.document_version_id, list(deps)
        )
        if blockers:
            state = ChecklistAnswerState.INSUFFICIENT_EVIDENCE
            rationale = "Dependent references not satisfied; independent items may still run"
            comment = "; ".join(b["message"] for b in blockers)
            ai_proposal.update(
                {
                    "answer": state,
                    "reference_blockers": blockers,
                    "note": "missing/critical refs → INSUFFICIENT_EVIDENCE (not NO)",
                }
            )
            return await _upsert_answer(
                session,
                run,
                item,
                state=state,
                rationale=rationale,
                confidence=None,
                ai_proposal=ai_proposal,
                chapter_text=None,
                comment_text=comment,
                cells=cells,
                evidence_ids=[],
                pack=pack,
            )

    try:
        if method == ChecklistMethod.DETERMINISTIC_RULE:
            result = run_deterministic_rule(
                method_config.get("rule") or "",
                method_config,
                pack,
                full_scan=full_scan,
                applicability_yes=applicability_yes,
                primary_doc_type=primary_doc_type,
                pinned_doc_types=pinned_doc_types,
            )
            rule_name = method_config.get("rule") or ""
            if rule_name == "dataicd_applicability":
                # Map applicability YES/NO → Is Applicable only; conformity Answer = NA if not applicable
                is_applicable_value = (
                    "Yes"
                    if result.state == ChecklistAnswerState.YES
                    else "No"
                    if result.state == ChecklistAnswerState.NO
                    else "NA"
                )
                if result.state == ChecklistAnswerState.YES:
                    state = ChecklistAnswerState.YES
                    rationale = result.rationale
                else:
                    state = ChecklistAnswerState.NA
                    rationale = result.rationale + " | conformity Answer=NA (not written into Is Applicable)"
                evidence_ids = result.evidence_ids
                subcheck_results = result.subcheck_results
                chapter = result.chapter_text
                comment = result.comment_text
                ai_proposal.update(
                    {
                        "answer": state,
                        "is_applicable": is_applicable_value,
                        "applicability_state": result.state,
                        "subchecks": subcheck_results,
                        "evidence_ids": evidence_ids,
                        "full_scan": full_scan,
                        "note": "applicability vs conformity kept separate",
                    }
                )
            else:
                # Propagate run-level applicability onto items that declare is_applicable cells
                if cells.get("is_applicable") and applicability_yes is not None:
                    is_applicable_value = "Yes" if applicability_yes else "No"
                state, extra = enforce_answer_semantics(
                    result.state,
                    subchecks=result.subcheck_results
                    or [{"id": s["id"], "passed": True} for s in subchecks_def],
                    inapplicability_rationale=(
                        "Data ICD not applicable" if result.state == ChecklistAnswerState.NA else None
                    ),
                    valid_evidence_ids=result.evidence_ids,
                    invalid_evidence_ids=[],
                    confidence=None,
                )
                rationale = result.rationale + (f" | {extra}" if extra else "")
                evidence_ids = result.evidence_ids
                subcheck_results = result.subcheck_results
                chapter = result.chapter_text
                comment = result.comment_text
                ai_proposal.update(
                    {
                        "answer": state,
                        "is_applicable": is_applicable_value,
                        "subchecks": subcheck_results,
                        "evidence_ids": evidence_ids,
                        "full_scan": full_scan,
                    }
                )

        elif method == ChecklistMethod.TRACEABILITY:
            rule_name = method_config.get("rule") or ""
            if rule_name.startswith("seci_"):
                from app.services.seci_rules import run_seci_traceability

                result = run_seci_traceability(rule_name, method_config, pack)
            else:
                result = run_traceability_full_scan(
                    list(method_config.get("required_keywords") or []), pack
                )
            state = result.state
            rationale = result.rationale
            evidence_ids = result.evidence_ids
            subcheck_results = result.subcheck_results
            chapter = result.chapter_text
            comment = result.comment_text
            ai_proposal.update(
                {"answer": state, "subchecks": subcheck_results, "evidence_ids": evidence_ids}
            )

        elif method == ChecklistMethod.EXTERNAL_EVIDENCE:
            meta_key = method_config.get("meta_key") or "external_evidence_document_version_ids"
            external_ids = (run.meta or {}).get(meta_key) or []
            if not external_ids:
                state = ChecklistAnswerState.INSUFFICIENT_EVIDENCE
                rationale = (
                    "No external evidence linked on review run "
                    "(missing evidence ≠ NA)"
                )
            else:
                state = ChecklistAnswerState.MANUAL_REVIEW
                rationale = f"External evidence linked ({len(external_ids)}); human confirmation required"
            ai_proposal.update({"answer": state, "external_ids": external_ids})

        elif method == ChecklistMethod.MANUAL_REVIEW:
            if method_config.get("gate_on_applicability") and applicability_yes is False:
                state = ChecklistAnswerState.NA
                rationale = "Not applicable — conformity Answer=NA (Is Applicable=No)"
                is_applicable_value = "No"
                comment = "Skipped manual conformity review; applicability is No"
            else:
                state = ChecklistAnswerState.MANUAL_REVIEW
                rationale = "Item requires human review (AI proposal only; not approved)"
                if cells.get("is_applicable") and applicability_yes is not None:
                    is_applicable_value = "Yes" if applicability_yes else "No"
            ai_proposal.update({"answer": state, "is_applicable": is_applicable_value})

        elif method == ChecklistMethod.CROSS_DOCUMENT:
            rule_name = method_config.get("rule") or ""
            if rule_name:
                from app.services.seci_rules import run_seci_cross_document

                result = run_seci_cross_document(rule_name, method_config, pack)
                state = result.state
                rationale = result.rationale
                evidence_ids = result.evidence_ids
                subcheck_results = result.subcheck_results
                chapter = result.chapter_text
                comment = result.comment_text
                ai_proposal.update(
                    {
                        "answer": state,
                        "subchecks": subcheck_results,
                        "evidence_ids": evidence_ids,
                        "pinned_document_version_ids": [
                            str(v) for v in (pack.pinned_document_version_ids or [])
                        ],
                    }
                )
            else:
                # Legacy SCS cross_document: reference deps already cleared above
                state = ChecklistAnswerState.YES
                rationale = "Required reference dependencies resolved for cross-document item"
                evidence_ids = [e.evidence_id for e in pack.items[:3]]
                ai_proposal.update({"answer": state, "evidence_ids": evidence_ids})

        elif method == ChecklistMethod.DOCUMENT_CONTENT:
            terms = list(method_config.get("evidence_query_terms") or [])
            limit = None if full_scan else int(method_config.get("max_evidence_chunks") or 12)
            selected = filter_evidence(pack, terms, limit=limit, full_scan=full_scan)
            if not selected:
                state = ChecklistAnswerState.INSUFFICIENT_EVIDENCE
                rationale = "No evidence chunks matched query terms (missing search ≠ NO)"
                ai_proposal.update({"answer": state, "evidence_ids": []})
            else:
                proposal = await ollama_checklist_evaluate(
                    settings,
                    question=item.prompt,
                    acceptance_criteria=schema.get("acceptance_criteria") or "",
                    subchecks=subchecks_def,
                    evidence=[e.to_prompt_dict() for e in selected],
                )
                valid, invalid = verify_evidence_citations(
                    proposed_ids=proposal.evidence_ids, pack=pack
                )
                state, extra = enforce_answer_semantics(
                    proposal.answer,
                    subchecks=[s.model_dump() for s in proposal.subchecks],
                    inapplicability_rationale=proposal.inapplicability_rationale,
                    valid_evidence_ids=valid,
                    invalid_evidence_ids=invalid,
                    confidence=proposal.confidence,
                )
                rationale = proposal.rationale + (f" | {extra}" if extra else "")
                evidence_ids = valid
                subcheck_results = [s.model_dump() for s in proposal.subchecks]
                chapter = proposal.chapter
                comment = proposal.comment
                confidence = proposal.confidence
                ai_proposal.update(
                    {
                        "answer": proposal.answer,
                        "enforced_answer": state,
                        "subchecks": subcheck_results,
                        "evidence_ids": evidence_ids,
                        "invalid_evidence_ids": invalid,
                        "confidence": confidence,
                        "inapplicability_rationale": proposal.inapplicability_rationale,
                        "raw": proposal.model_dump(mode="json"),
                    }
                )
        else:
            state = ChecklistAnswerState.ERROR
            rationale = f"Unsupported method: {method}"
            ai_proposal.update({"answer": state})

    except Exception as exc:  # noqa: BLE001
        logger.exception("checklist item %s failed", item.item_key)
        state = ChecklistAnswerState.ERROR
        rationale = f"Evaluation error: {exc}"
        ai_proposal.update({"answer": state, "error": str(exc)})

    if is_applicable_value is not None:
        ai_proposal.setdefault("is_applicable", is_applicable_value)

    return await _upsert_answer(
        session,
        run,
        item,
        state=state,
        rationale=rationale,
        confidence=confidence,
        ai_proposal=ai_proposal,
        chapter_text=chapter,
        comment_text=comment,
        cells=cells,
        evidence_ids=evidence_ids,
        pack=pack,
    )


async def _upsert_answer(
    session: AsyncSession,
    run: ChecklistRun,
    item: ChecklistItem,
    *,
    state: str,
    rationale: str,
    confidence: float | None,
    ai_proposal: dict[str, Any],
    chapter_text: str | None,
    comment_text: str | None,
    cells: dict[str, Any],
    evidence_ids: list[str],
    pack: EvidencePack,
) -> ChecklistAnswer:
    existing = await session.scalar(
        select(ChecklistAnswer).where(
            ChecklistAnswer.run_id == run.id, ChecklistAnswer.item_id == item.id
        )
    )
    if existing is None:
        answer = ChecklistAnswer(
            id=uuid.uuid4(),
            run_id=run.id,
            item_id=item.id,
        )
        session.add(answer)
    else:
        answer = existing
        # wipe prior evidence links for this answer
        old_links = (
            await session.scalars(
                select(EvidenceLink).where(EvidenceLink.checklist_answer_id == answer.id)
            )
        ).all()
        for link in old_links:
            await session.delete(link)

    # human_decision stays untouched (Phase 5) — AI proposal stored separately
    if answer.human_decision is None:
        answer.state = state
    answer.confidence = confidence
    answer.rationale = rationale
    answer.raw_model_output = ai_proposal
    answer.ai_proposal = {
        **ai_proposal,
        "proposed_state": state,
        "proposed_at": datetime.now(timezone.utc).isoformat(),
    }
    answer.chapter_text = chapter_text
    answer.comment_text = comment_text
    answer.excel_answer_cell = cells.get("answer") or item.excel_cell
    answer.excel_chapter_cell = cells.get("chapter")
    answer.excel_comment_cell = cells.get("comment")
    await session.flush()

    by_id = pack.by_id()
    for eid in evidence_ids:
        ev = by_id.get(eid)
        if not ev:
            continue
        session.add(
            EvidenceLink(
                id=uuid.uuid4(),
                checklist_answer_id=answer.id,
                document_version_id=ev.document_version_id,
                quote=ev.quote[:4000],
                locator=ev.locator,
                qdrant_point_id=None,
            )
        )
    await session.flush()
    return answer


async def run_checklist_review(
    session: AsyncSession,
    settings: Settings,
    *,
    project_id: uuid.UUID,
    document_version_id: uuid.UUID,
    definition_key: str = "software_code_standard",
    pinned_standard_version_ids: list[str] | None = None,
    pinned_document_version_ids: list[str] | None = None,
    external_evidence_document_version_ids: list[str] | None = None,
) -> dict[str, Any]:
    document_version = await session.get(DocumentVersion, document_version_id)
    if document_version is None:
        raise RuntimeError("document_version not found")
    document = await session.get(Document, document_version.document_id)
    if document is None:
        raise RuntimeError("document not found")
    if document.project_id != project_id:
        raise RuntimeError("document not in project")

    from app.services.checklist_catalog import ensure_catalog_seeded

    definition = await ensure_catalog_seeded(session, definition_key)

    items = (
        await session.scalars(
            select(ChecklistItem)
            .where(ChecklistItem.definition_id == definition.id)
            .order_by(ChecklistItem.sort_order.asc())
        )
    ).all()

    # Pin standard versions: explicit arg, else from open reference review, else project set
    pinned = list(pinned_standard_version_ids or [])
    if not pinned:
        reviews = (
            await session.scalars(select(Review).where(Review.project_id == project_id))
        ).all()
        for r in reviews:
            meta = r.meta or {}
            if (
                meta.get("kind") == "reference_validation"
                and meta.get("document_version_id") == str(document_version_id)
            ):
                pinned = list(meta.get("pinned_standard_version_ids") or [])
                break
    if not pinned:
        pinned = [
            str(x)
            for x in (
                await session.scalars(
                    select(ProjectStandardSet.standard_version_id).where(
                        ProjectStandardSet.project_id == project_id
                    )
                )
            ).all()
        ]

    # Pin peer document versions for cross-document (SECI / multi-doc) reviews
    peer_ids: list[uuid.UUID] = []
    for raw in pinned_document_version_ids or []:
        try:
            vid = uuid.UUID(str(raw))
        except ValueError:
            continue
        if vid == document_version_id:
            continue
        peer = await session.get(DocumentVersion, vid)
        if peer is None:
            continue
        peer_doc = await session.get(Document, peer.document_id)
        if peer_doc is None or peer_doc.project_id != project_id:
            continue
        peer_ids.append(vid)

    run = ChecklistRun(
        id=uuid.uuid4(),
        project_id=project_id,
        definition_id=definition.id,
        document_version_id=document_version_id,
        status="running",
        started_at=datetime.now(timezone.utc),
        meta={
            "pinned_standard_version_ids": pinned,
            "pinned_document_version_id": str(document_version_id),
            "pinned_document_version_ids": [str(document_version_id)]
            + [str(v) for v in peer_ids],
            "definition_key": definition.key,
            "definition_version": definition.version_label,
            "external_evidence_document_version_ids": list(
                external_evidence_document_version_ids or []
            ),
            "template_gap": (definition.meta or {}).get("template_gap"),
        },
    )
    session.add(run)
    await session.flush()

    units = _load_units_for_version(document_version)
    pack = build_evidence_pack_from_units(
        project_id=project_id,
        document_version_id=document_version.id,
        version_label=document_version.version_label,
        content_sha256=document_version.content_sha256,
        units=units,
        doc_type=document.doc_type,
        pinned_document_version_ids=peer_ids,
    )
    peer_packs: list[tuple[EvidencePack, str | None]] = []
    for vid in peer_ids:
        peer = await session.get(DocumentVersion, vid)
        if peer is None:
            continue
        peer_doc = await session.get(Document, peer.document_id)
        peer_units = _load_units_for_version(peer)
        peer_pack = build_evidence_pack_from_units(
            project_id=project_id,
            document_version_id=peer.id,
            version_label=peer.version_label,
            content_sha256=peer.content_sha256,
            units=peer_units,
            doc_type=peer_doc.doc_type if peer_doc else None,
        )
        peer_packs.append((peer_pack, peer_doc.doc_type if peer_doc else None))
    if peer_packs:
        pack = merge_evidence_packs(pack, peer_packs)

    answers = []
    applicability_yes: bool | None = None
    for item in items:
        ans = await evaluate_item(
            session,
            settings,
            run=run,
            item=item,
            pack=pack,
            applicability_yes=applicability_yes,
        )
        answers.append(ans)
        # Track DataICD applicability from the dedicated applicability item
        if item.item_key == "DICD-Q01" or (
            (item.schema_json or {}).get("method_config") or {}
        ).get("rule") == "dataicd_applicability":
            app_val = (ans.ai_proposal or {}).get("is_applicable")
            if app_val == "Yes":
                applicability_yes = True
            elif app_val == "No":
                applicability_yes = False

    run.status = "succeeded"
    run.finished_at = datetime.now(timezone.utc)
    meta = dict(run.meta or {})
    meta["answer_counts"] = _count_states(answers)
    meta["applicability_yes"] = applicability_yes
    run.meta = meta
    flag_modified(run, "meta")

    return {
        "checklist_run_id": str(run.id),
        "definition_key": definition.key,
        "item_count": len(items),
        "answer_counts": meta["answer_counts"],
        "pinned_standard_version_ids": pinned,
        "pinned_document_version_ids": meta["pinned_document_version_ids"],
        "applicability_yes": applicability_yes,
    }


def _count_states(answers: list[ChecklistAnswer]) -> dict[str, int]:
    out: dict[str, int] = {}
    for a in answers:
        out[a.state] = out.get(a.state, 0) + 1
    return out
