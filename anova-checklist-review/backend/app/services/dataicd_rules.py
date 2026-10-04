"""Deterministic DataICD rules. Applicability is evaluated separately from conformity."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from app.core.enums import ChecklistAnswerState
from app.services.checklist_rules import RuleResult
from app.services.evidence import EvidenceItem, EvidencePack

# SIG-001 | name | float | m/s   OR CSV-ish rows
_ICD_ROW = re.compile(
    r"(?P<id>(?:SIG|PARAM|ICD)-[A-Z0-9]+)\s*[|,;\t]\s*"
    r"(?P<name>[^|,;\t]+)\s*[|,;\t]\s*"
    r"(?P<dtype>[^|,;\t]+)\s*[|,;\t]\s*"
    r"(?P<units>[^|,;\t\n]+)",
    re.IGNORECASE,
)
_ID_ONLY = re.compile(r"\b(?:SIG|PARAM|ICD)-[A-Z0-9]+\b", re.IGNORECASE)


@dataclass
class IcdRecord:
    record_id: str
    name: str
    dtype: str
    units: str
    evidence_id: str
    raw: str


def parse_icd_records(pack: EvidencePack) -> list[IcdRecord]:
    records: list[IcdRecord] = []
    seen: set[tuple[str, str]] = set()
    for ev in pack.items:
        for m in _ICD_ROW.finditer(ev.quote or ""):
            rid = m.group("id").upper()
            key = (rid, ev.evidence_id)
            if key in seen:
                continue
            seen.add(key)
            records.append(
                IcdRecord(
                    record_id=rid,
                    name=(m.group("name") or "").strip(),
                    dtype=(m.group("dtype") or "").strip(),
                    units=(m.group("units") or "").strip(),
                    evidence_id=ev.evidence_id,
                    raw=m.group(0),
                )
            )
    return records


def evaluate_dataicd_applicability(
    config: dict[str, Any],
    pack: EvidencePack,
    *,
    primary_doc_type: str | None,
    pinned_doc_types: list[str] | None = None,
) -> RuleResult:
    """Return applicability as YES/NO in state; caller maps to Is Applicable column only."""
    applicable_types = {
        t.lower() for t in (config.get("applicable_doc_types") or ["icd", "data_icd"])
    }
    patterns = [re.compile(p) for p in (config.get("icd_marker_patterns") or [])]
    types_seen = {((primary_doc_type or "")).lower()}
    for t in pinned_doc_types or []:
        types_seen.add((t or "").lower())
    type_hit = bool(types_seen & applicable_types)
    text_hit = False
    evidence_ids: list[str] = []
    if patterns:
        for ev in pack.items:
            if any(p.search(ev.quote or "") for p in patterns):
                text_hit = True
                evidence_ids.append(ev.evidence_id)
                if len(evidence_ids) >= 5:
                    break
    applicable = type_hit or text_hit
    sub = [
        {
            "id": "has-icd-doc",
            "passed": applicable,
            "detail": f"type_hit={type_hit} text_hit={text_hit} types={sorted(types_seen)}",
        }
    ]
    if applicable:
        return RuleResult(
            state=ChecklistAnswerState.YES,
            rationale="Data ICD appears applicable (doc type and/or ICD markers)",
            subcheck_results=sub,
            evidence_ids=evidence_ids[:10],
            comment_text="Applicability=Yes (not a conformity judgment)",
        )
    return RuleResult(
        state=ChecklistAnswerState.NO,
        rationale="No ICD doc_type or ICD markers — Data ICD not applicable",
        subcheck_results=sub,
        evidence_ids=[],
        comment_text="Applicability=No; conformity Answer should be NA, not written into Is Applicable",
    )


def _gate_not_applicable() -> RuleResult:
    return RuleResult(
        state=ChecklistAnswerState.NA,
        rationale="Data ICD not applicable — conformity Answer=NA (Is Applicable stays No)",
        subcheck_results=[{"id": "applicability-gate", "passed": True, "detail": "not applicable"}],
        comment_text="Skipped conformity check because Is Applicable=No",
    )


def run_dataicd_rule(
    rule_name: str,
    config: dict[str, Any],
    pack: EvidencePack,
    *,
    applicability_yes: bool | None,
    primary_doc_type: str | None = None,
    pinned_doc_types: list[str] | None = None,
) -> RuleResult:
    if rule_name == "dataicd_applicability":
        return evaluate_dataicd_applicability(
            config, pack, primary_doc_type=primary_doc_type, pinned_doc_types=pinned_doc_types
        )

    if config.get("gate_on_applicability") and applicability_yes is False:
        return _gate_not_applicable()

    if not pack.items:
        return RuleResult(
            ChecklistAnswerState.INSUFFICIENT_EVIDENCE,
            "No extractable units for DataICD evaluation (missing search ≠ NO)",
        )

    records = parse_icd_records(pack)
    if rule_name == "dataicd_all_records_have_id":
        return _all_have_id(pack, records)
    if rule_name == "dataicd_unique_ids":
        return _unique_ids(records)
    if rule_name == "dataicd_all_records_have_datatype":
        return _all_have_field(records, "dtype", "all-have-dtype")
    if rule_name == "dataicd_all_records_have_units":
        return _all_have_units(records)
    return RuleResult(
        ChecklistAnswerState.ERROR,
        f"Unknown DataICD rule: {rule_name}",
    )


def _all_have_id(pack: EvidencePack, records: list[IcdRecord]) -> RuleResult:
    if not records:
        # Fallback: any bare IDs still count as partial structure
        bare = []
        for ev in pack.items:
            if _ID_ONLY.search(ev.quote or ""):
                bare.append(ev.evidence_id)
        if not bare:
            return RuleResult(
                ChecklistAnswerState.INSUFFICIENT_EVIDENCE,
                "No ICD records parsed (missing records ≠ NO)",
                [{"id": "all-records-have-id", "passed": False, "detail": "0 records"}],
            )
        return RuleResult(
            ChecklistAnswerState.YES,
            f"Found {len(bare)} units with signal/parameter IDs",
            [{"id": "all-records-have-id", "passed": True, "detail": f"bare_ids_units={len(bare)}"}],
            evidence_ids=bare[:20],
            chapter_text="ICD records",
        )
    missing = [r for r in records if not r.record_id]
    sub = [
        {
            "id": "all-records-have-id",
            "passed": not missing,
            "detail": f"records={len(records)} missing_id={len(missing)}",
        }
    ]
    if missing:
        return RuleResult(
            ChecklistAnswerState.NO,
            f"{len(missing)} records missing identifiers",
            sub,
            evidence_ids=[r.evidence_id for r in missing[:20]],
        )
    return RuleResult(
        ChecklistAnswerState.YES,
        f"All {len(records)} ICD records have identifiers (full scan)",
        sub,
        evidence_ids=[r.evidence_id for r in records[:20]],
        chapter_text="ICD records",
    )


def _unique_ids(records: list[IcdRecord]) -> RuleResult:
    if not records:
        return RuleResult(
            ChecklistAnswerState.INSUFFICIENT_EVIDENCE,
            "No ICD records to check uniqueness (missing ≠ NO)",
            [{"id": "unique-ids", "passed": False, "detail": "0 records"}],
        )
    counts: dict[str, list[IcdRecord]] = {}
    for r in records:
        counts.setdefault(r.record_id, []).append(r)
    dupes = {k: v for k, v in counts.items() if len(v) > 1}
    sub = [
        {
            "id": "unique-ids",
            "passed": not dupes,
            "detail": f"unique={len(counts)} duplicates={list(dupes)[:10]}",
        }
    ]
    if dupes:
        ev = [r.evidence_id for rs in dupes.values() for r in rs][:30]
        return RuleResult(
            ChecklistAnswerState.NO,
            f"Duplicate ICD identifiers: {sorted(dupes)[:10]}",
            sub,
            evidence_ids=ev,
        )
    return RuleResult(
        ChecklistAnswerState.YES,
        f"All {len(records)} identifiers unique (full scan)",
        sub,
        evidence_ids=[r.evidence_id for r in records[:15]],
        chapter_text="ICD identifiers",
    )


def _all_have_field(records: list[IcdRecord], field: str, sub_id: str) -> RuleResult:
    if not records:
        return RuleResult(
            ChecklistAnswerState.INSUFFICIENT_EVIDENCE,
            f"No ICD records to check {field} (missing ≠ NO)",
            [{"id": sub_id, "passed": False, "detail": "0 records"}],
        )
    missing = [r for r in records if not getattr(r, field, "").strip()]
    sub = [
        {
            "id": sub_id,
            "passed": not missing,
            "detail": f"records={len(records)} missing={len(missing)}",
        }
    ]
    if missing:
        return RuleResult(
            ChecklistAnswerState.NO,
            f"{len(missing)}/{len(records)} records missing {field}",
            sub,
            evidence_ids=[r.evidence_id for r in missing[:20]],
        )
    return RuleResult(
        ChecklistAnswerState.YES,
        f"All {len(records)} records have {field} (full scan)",
        sub,
        evidence_ids=[r.evidence_id for r in records[:15]],
        chapter_text="ICD fields",
    )


def _all_have_units(records: list[IcdRecord]) -> RuleResult:
    if not records:
        return RuleResult(
            ChecklistAnswerState.INSUFFICIENT_EVIDENCE,
            "No ICD records to check units (missing ≠ NO)",
            [{"id": "all-have-units", "passed": False, "detail": "0 records"}],
        )
    missing = []
    for r in records:
        u = (r.units or "").strip()
        if not u:
            missing.append(r)
    sub = [
        {
            "id": "all-have-units",
            "passed": not missing,
            "detail": f"records={len(records)} missing_units={len(missing)}",
        }
    ]
    if missing:
        return RuleResult(
            ChecklistAnswerState.NO,
            f"{len(missing)}/{len(records)} records missing units (use N/A if dimensionless)",
            sub,
            evidence_ids=[r.evidence_id for r in missing[:20]],
        )
    return RuleResult(
        ChecklistAnswerState.YES,
        f"All {len(records)} records have units or N/A (full scan)",
        sub,
        evidence_ids=[r.evidence_id for r in records[:15]],
        chapter_text="ICD units",
    )


# silence unused import for type checkers
_ = EvidenceItem
