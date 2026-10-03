"""Deterministic checklist rules (Python). Missing search ≠ NO."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from app.core.enums import ChecklistAnswerState
from app.services.evidence import EvidenceItem, EvidencePack


@dataclass
class RuleResult:
    state: str
    rationale: str
    subcheck_results: list[dict[str, Any]] = field(default_factory=list)
    evidence_ids: list[str] = field(default_factory=list)
    chapter_text: str | None = None
    comment_text: str | None = None


def run_deterministic_rule(
    rule_name: str,
    config: dict[str, Any],
    pack: EvidencePack,
    *,
    full_scan: bool,
    applicability_yes: bool | None = None,
    primary_doc_type: str | None = None,
    pinned_doc_types: list[str] | None = None,
) -> RuleResult:
    # DataICD rules may run even when pack is empty (applicability → No)
    if rule_name.startswith("dataicd_"):
        from app.services.dataicd_rules import run_dataicd_rule

        return run_dataicd_rule(
            rule_name,
            config,
            pack,
            applicability_yes=applicability_yes,
            primary_doc_type=primary_doc_type,
            pinned_doc_types=pinned_doc_types,
        )
    if not pack.items:
        return RuleResult(
            state=ChecklistAnswerState.INSUFFICIENT_EVIDENCE,
            rationale="No extractable document units available to evaluate (missing search ≠ NO)",
        )
    if rule_name == "header_copyright_all_units":
        return _header_copyright_all_units(config, pack)
    if rule_name == "forbidden_pattern_absent_all_units":
        return _forbidden_absent(config, pack)
    if rule_name == "keyword_present_full_scan":
        return _keyword_present(config, pack, full_scan=True)
    return RuleResult(
        state=ChecklistAnswerState.ERROR,
        rationale=f"Unknown deterministic rule: {rule_name}",
    )


def _compile_patterns(patterns: list[str]) -> list[re.Pattern[str]]:
    return [re.compile(p) for p in patterns]


def _header_copyright_all_units(config: dict[str, Any], pack: EvidencePack) -> RuleResult:
    header_lines = int(config.get("header_lines") or 40)
    patterns = _compile_patterns(config.get("patterns") or [])
    failures: list[EvidenceItem] = []
    successes: list[str] = []
    for ev in pack.items:
        head = "\n".join(ev.quote.splitlines()[:header_lines])
        ok_block = bool(head.strip())
        ok_copy = any(p.search(head) for p in patterns)
        if ok_block and ok_copy:
            successes.append(ev.evidence_id)
        else:
            failures.append(ev)
    sub = [
        {
            "id": "hdr-present",
            "passed": len(failures) == 0 and bool(pack.items),
            "detail": f"units={len(pack.items)} failures={len(failures)}",
        },
        {
            "id": "hdr-copyright",
            "passed": len(failures) == 0 and bool(pack.items),
            "detail": "copyright/ownership marker in header window",
        },
    ]
    if not pack.items:
        return RuleResult(
            ChecklistAnswerState.INSUFFICIENT_EVIDENCE,
            "No units to scan",
            sub,
        )
    if failures:
        return RuleResult(
            ChecklistAnswerState.NO,
            f"{len(failures)}/{len(pack.items)} units failed header/copyright subchecks",
            sub,
            evidence_ids=[f.evidence_id for f in failures[:20]] + successes[:5],
            chapter_text="file header",
        )
    return RuleResult(
        ChecklistAnswerState.YES,
        "All units satisfy header copyright subchecks (full scan)",
        sub,
        evidence_ids=successes[:30],
        chapter_text="file header",
    )


def _forbidden_absent(config: dict[str, Any], pack: EvidencePack) -> RuleResult:
    patterns = _compile_patterns(config.get("patterns") or [])
    hits: list[EvidenceItem] = []
    for ev in pack.items:
        if any(p.search(ev.quote) for p in patterns):
            hits.append(ev)
    sub = [
        {
            "id": "no-todo",
            "passed": len(hits) == 0,
            "detail": f"hits={len(hits)} across {len(pack.items)} units",
        }
    ]
    if hits:
        return RuleResult(
            ChecklistAnswerState.NO,
            f"Forbidden markers found in {len(hits)} units (full scan)",
            sub,
            evidence_ids=[h.evidence_id for h in hits[:30]],
        )
    return RuleResult(
        ChecklistAnswerState.YES,
        "No forbidden markers in any unit (full scan)",
        sub,
        evidence_ids=[e.evidence_id for e in pack.items[:5]],
    )


def _keyword_present(
    config: dict[str, Any], pack: EvidencePack, *, full_scan: bool
) -> RuleResult:
    patterns = _compile_patterns(config.get("patterns") or [])
    hits = [ev for ev in pack.items if any(p.search(ev.quote) for p in patterns)]
    if not hits:
        # Missing search hit is INSUFFICIENT_EVIDENCE, not NO
        return RuleResult(
            ChecklistAnswerState.INSUFFICIENT_EVIDENCE,
            "Required keywords not found in full document scan (missing search ≠ NO)",
            [{"id": "keyword", "passed": False, "detail": "no hits"}],
            evidence_ids=[],
        )
    return RuleResult(
        ChecklistAnswerState.YES,
        f"Required keywords found in {len(hits)} units",
        [{"id": "keyword", "passed": True, "detail": f"hits={len(hits)}"}],
        evidence_ids=[h.evidence_id for h in hits[:20]],
        chapter_text=str((hits[0].locator or {}).get("kind") or ""),
    )


def run_traceability_full_scan(
    required_keywords: list[str], pack: EvidencePack
) -> RuleResult:
    if not pack.items:
        return RuleResult(
            ChecklistAnswerState.INSUFFICIENT_EVIDENCE,
            "No units available for traceability full scan",
        )
    missing = []
    evidence_ids: list[str] = []
    for kw in required_keywords:
        hit = next((e for e in pack.items if kw.lower() in e.quote.lower()), None)
        if hit is None:
            missing.append(kw)
        else:
            evidence_ids.append(hit.evidence_id)
    sub = [
        {
            "id": "rule-section-map",
            "passed": not missing,
            "detail": f"missing={missing}" if missing else "all keywords mapped",
        }
    ]
    if missing:
        return RuleResult(
            ChecklistAnswerState.INSUFFICIENT_EVIDENCE,
            f"Traceability full scan missing keywords: {missing}",
            sub,
            evidence_ids=evidence_ids,
        )
    return RuleResult(
        ChecklistAnswerState.YES,
        "All required rule keywords mapped to locator-backed units",
        sub,
        evidence_ids=evidence_ids,
    )
