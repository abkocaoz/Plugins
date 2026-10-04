from __future__ import annotations

import uuid

from app.core.enums import ChecklistAnswerState
from app.services.checklist_rules import run_deterministic_rule, run_traceability_full_scan
from app.services.evidence import EvidenceItem, EvidencePack


def _pack(texts: list[str]) -> EvidencePack:
    pid = uuid.uuid4()
    vid = uuid.uuid4()
    items = []
    for i, t in enumerate(texts):
        items.append(
            EvidenceItem(
                evidence_id=f"ev_{i}",
                document_version_id=vid,
                project_id=pid,
                quote=t,
                locator={"kind": "code_lines", "line_start": i + 1},
                revision="1",
                content_sha256="abc",
            )
        )
    return EvidencePack(pid, vid, "1", "abc", items)


def test_todo_full_scan_yes_and_no():
    yes = run_deterministic_rule(
        "forbidden_pattern_absent_all_units",
        {"patterns": [r"\bTODO\b"]},
        _pack(["int main() { return 0; }"]),
        full_scan=True,
    )
    assert yes.state == ChecklistAnswerState.YES
    no = run_deterministic_rule(
        "forbidden_pattern_absent_all_units",
        {"patterns": [r"\bTODO\b"]},
        _pack(["// TODO fix later", "ok"]),
        full_scan=True,
    )
    assert no.state == ChecklistAnswerState.NO


def test_missing_keyword_is_insufficient_not_no():
    result = run_deterministic_rule(
        "keyword_present_full_scan",
        {"patterns": ["(?i)coding standard"]},
        _pack(["unrelated text only"]),
        full_scan=True,
    )
    assert result.state == ChecklistAnswerState.INSUFFICIENT_EVIDENCE


def test_header_copyright_all_units():
    good = "/* Copyright (c) Acme Corp */\nint x;\n"
    bad = "int y;\n"
    result = run_deterministic_rule(
        "header_copyright_all_units",
        {
            "header_lines": 10,
            "patterns": ["(?i)copyright", "(?i)\\(c\\)"],
        },
        _pack([good, bad]),
        full_scan=True,
    )
    assert result.state == ChecklistAnswerState.NO


def test_traceability_full_scan():
    pack = _pack(
        [
            "Naming conventions use camelCase",
            "Every function has a comment",
            "Error handling returns codes",
            "Interface contracts documented",
        ]
    )
    ok = run_traceability_full_scan(
        ["naming", "comment", "error handling", "interface"], pack
    )
    assert ok.state == ChecklistAnswerState.YES
    miss = run_traceability_full_scan(["naming", "memory safety"], pack)
    assert miss.state == ChecklistAnswerState.INSUFFICIENT_EVIDENCE
