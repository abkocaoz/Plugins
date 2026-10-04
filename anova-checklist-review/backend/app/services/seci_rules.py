"""SECI cross-document / traceability rules across pinned document versions."""

from __future__ import annotations

import re
from typing import Any

from app.core.enums import ChecklistAnswerState
from app.services.checklist_rules import RuleResult
from app.services.evidence import EvidenceItem, EvidencePack


def _items_for_doc_types(pack: EvidencePack, doc_types: list[str]) -> list[EvidenceItem]:
    wanted = {t.lower() for t in doc_types if t}
    if not wanted:
        return list(pack.items)
    out: list[EvidenceItem] = []
    for ev in pack.items:
        dtype = (ev.locator or {}).get("doc_type") or (ev.locator or {}).get("extra", {}).get(
            "doc_type"
        )
        if dtype and str(dtype).lower() in wanted:
            out.append(ev)
    return out


def _extract_ids(text: str, pattern: str) -> set[str]:
    return {m.group(0).upper() for m in re.finditer(pattern, text or "")}


def run_seci_cross_document(
    rule_name: str,
    config: dict[str, Any],
    pack: EvidencePack,
) -> RuleResult:
    if rule_name == "seci_pinned_versions_available":
        return _pinned_versions_available(pack)
    if rule_name == "seci_ids_in_peer_docs":
        return _ids_in_peer_docs(config, pack)
    return RuleResult(
        ChecklistAnswerState.ERROR,
        f"Unknown SECI cross_document rule: {rule_name}",
    )


def run_seci_traceability(
    rule_name: str,
    config: dict[str, Any],
    pack: EvidencePack,
) -> RuleResult:
    if rule_name == "seci_shall_trace_to_peers":
        return _shall_trace_to_peers(config, pack)
    # Fallback to keyword list if provided
    if config.get("required_keywords"):
        from app.services.checklist_rules import run_traceability_full_scan

        return run_traceability_full_scan(list(config["required_keywords"]), pack)
    return RuleResult(
        ChecklistAnswerState.ERROR,
        f"Unknown SECI traceability rule: {rule_name}",
    )


def _pinned_versions_available(pack: EvidencePack) -> RuleResult:
    pinned = list(pack.pinned_document_version_ids or [])
    if not pinned:
        # Primary alone is acceptable but note insufficiency for true cross-doc
        if pack.items:
            return RuleResult(
                ChecklistAnswerState.INSUFFICIENT_EVIDENCE,
                "No additional document versions pinned on the review run for cross-document comparison",
                [
                    {
                        "id": "pins-present",
                        "passed": False,
                        "detail": f"primary={pack.document_version_id} peers=0",
                    }
                ],
                evidence_ids=[e.evidence_id for e in pack.items[:3]],
            )
        return RuleResult(
            ChecklistAnswerState.INSUFFICIENT_EVIDENCE,
            "No pinned document versions and no extractable units",
            [{"id": "pins-present", "passed": False, "detail": "empty"}],
        )
    missing: list[str] = []
    present: list[str] = []
    by_ver = pack.items_by_version or {}
    for vid in pinned:
        key = str(vid)
        units = by_ver.get(key) or []
        if not units:
            missing.append(key)
        else:
            present.append(key)
    # Primary should also be present
    primary_key = str(pack.document_version_id)
    if primary_key not in by_ver or not by_ver[primary_key]:
        if not pack.items:
            missing.append(primary_key)
    sub = [
        {
            "id": "pins-present",
            "passed": not missing,
            "detail": f"present={len(present)} missing={missing[:5]}",
        }
    ]
    if missing:
        return RuleResult(
            ChecklistAnswerState.INSUFFICIENT_EVIDENCE,
            f"Pinned document versions missing extractable units: {missing[:5]}",
            sub,
            evidence_ids=[e.evidence_id for e in pack.items[:5]],
        )
    return RuleResult(
        ChecklistAnswerState.YES,
        f"All {len(pinned)} pinned peer versions available (+ primary)",
        sub,
        evidence_ids=[e.evidence_id for e in pack.items[:5]],
        chapter_text="pinned versions",
    )


def _ids_in_peer_docs(config: dict[str, Any], pack: EvidencePack) -> RuleResult:
    id_pattern = config.get("id_pattern") or r"(?i)\b(?:SIG|PARAM|ICD)-[A-Z0-9]+\b"
    source_types = list(config.get("source_doc_types") or ["seci", "source"])
    target_types = list(config.get("target_doc_types") or ["icd", "data_icd"])

    source_items = _items_for_doc_types(pack, source_types)
    if not source_items:
        # Fall back to primary document units
        source_items = [
            e
            for e in pack.items
            if e.document_version_id == pack.document_version_id
        ] or list(pack.items)

    target_items = _items_for_doc_types(pack, target_types)
    if config.get("requires_pinned_peers") and not target_items:
        peers = [
            e
            for e in pack.items
            if e.document_version_id != pack.document_version_id
        ]
        if not peers:
            return RuleResult(
                ChecklistAnswerState.INSUFFICIENT_EVIDENCE,
                "No pinned peer ICD document units available for SECI ID comparison",
                [{"id": "ids-in-icd", "passed": False, "detail": "no peer units"}],
            )
        # If doc_types weren't tagged, use all non-primary peers as targets
        target_items = peers

    if not target_items:
        return RuleResult(
            ChecklistAnswerState.INSUFFICIENT_EVIDENCE,
            "No target ICD units to compare against (missing peer ≠ NO)",
            [{"id": "ids-in-icd", "passed": False, "detail": "no targets"}],
        )

    source_ids: set[str] = set()
    source_ev: list[str] = []
    for ev in source_items:
        ids = _extract_ids(ev.quote, id_pattern)
        if ids:
            source_ids |= ids
            source_ev.append(ev.evidence_id)

    if not source_ids:
        return RuleResult(
            ChecklistAnswerState.INSUFFICIENT_EVIDENCE,
            "No SECI signal/parameter IDs found in source document full scan",
            [{"id": "ids-in-icd", "passed": False, "detail": "0 source ids"}],
            evidence_ids=source_ev[:5],
        )

    target_text = "\n".join(ev.quote for ev in target_items)
    target_ids = _extract_ids(target_text, id_pattern)
    missing = sorted(source_ids - target_ids)
    present = sorted(source_ids & target_ids)
    sub = [
        {
            "id": "ids-in-icd",
            "passed": not missing,
            "detail": f"source={len(source_ids)} matched={len(present)} missing={missing[:15]}",
        }
    ]
    evidence_ids = source_ev[:10] + [e.evidence_id for e in target_items[:10]]
    if missing:
        return RuleResult(
            ChecklistAnswerState.NO,
            f"{len(missing)}/{len(source_ids)} SECI IDs missing from pinned ICD peers: {missing[:10]}",
            sub,
            evidence_ids=evidence_ids,
            chapter_text="SECI↔ICD IDs",
            comment_text=f"Missing: {', '.join(missing[:20])}",
        )
    return RuleResult(
        ChecklistAnswerState.YES,
        f"All {len(source_ids)} SECI IDs found in pinned ICD peer documents (full scan)",
        sub,
        evidence_ids=evidence_ids,
        chapter_text="SECI↔ICD IDs",
    )


def _shall_trace_to_peers(config: dict[str, Any], pack: EvidencePack) -> RuleResult:
    shall_re = re.compile(config.get("shall_pattern") or r"(?i)\bshall\b")
    peer_types = list(config.get("peer_doc_types") or ["icd", "data_icd", "source", "design"])

    primary_items = [
        e for e in pack.items if e.document_version_id == pack.document_version_id
    ] or list(pack.items)
    peer_items = _items_for_doc_types(pack, peer_types)
    if not peer_items:
        peer_items = [
            e for e in pack.items if e.document_version_id != pack.document_version_id
        ]

    shall_units = [e for e in primary_items if shall_re.search(e.quote or "")]
    if not shall_units:
        return RuleResult(
            ChecklistAnswerState.INSUFFICIENT_EVIDENCE,
            "No shall-style requirements found in primary SECI document (missing ≠ NO)",
            [{"id": "shall-map", "passed": False, "detail": "0 shall units"}],
        )
    if not peer_items:
        return RuleResult(
            ChecklistAnswerState.INSUFFICIENT_EVIDENCE,
            "No peer document units pinned for shall traceability",
            [{"id": "shall-map", "passed": False, "detail": "0 peers"}],
            evidence_ids=[e.evidence_id for e in shall_units[:5]],
        )

    peer_blob = "\n".join(e.quote.lower() for e in peer_items)
    unmapped: list[EvidenceItem] = []
    mapped_ids: list[str] = []
    for ev in shall_units:
        # Use distinctive tokens from the shall sentence (IDs or significant words)
        ids = _extract_ids(ev.quote, r"(?i)\b(?:SIG|PARAM|ICD)-[A-Z0-9]+\b")
        tokens = ids or {
            w.lower()
            for w in re.findall(r"[A-Za-z]{5,}", ev.quote)
            if w.lower() not in {"shall", "should", "must", "system", "software"}
        }
        if not tokens:
            unmapped.append(ev)
            continue
        if any(t.lower() in peer_blob for t in tokens):
            mapped_ids.append(ev.evidence_id)
        else:
            unmapped.append(ev)

    sub = [
        {
            "id": "shall-map",
            "passed": not unmapped,
            "detail": f"shall={len(shall_units)} mapped={len(mapped_ids)} unmapped={len(unmapped)}",
        }
    ]
    if unmapped:
        return RuleResult(
            ChecklistAnswerState.INSUFFICIENT_EVIDENCE,
            f"{len(unmapped)}/{len(shall_units)} shall statements lack peer-document hits",
            sub,
            evidence_ids=[e.evidence_id for e in unmapped[:20]] + mapped_ids[:5],
            comment_text="Unmapped shall units require peer evidence or human review",
        )
    return RuleResult(
        ChecklistAnswerState.YES,
        f"All {len(shall_units)} shall statements mapped to peer units (full scan)",
        sub,
        evidence_ids=mapped_ids[:30] + [e.evidence_id for e in peer_items[:5]],
        chapter_text="SECI shall trace",
    )
