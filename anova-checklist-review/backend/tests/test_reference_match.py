from __future__ import annotations

import uuid

from app.core.enums import ReferenceStatus
from app.models.entities import ExtractedReference
from app.services.reference_match import CatalogCandidate, match_reference


def _ref(**kwargs) -> ExtractedReference:
    base = dict(
        id=uuid.uuid4(),
        document_version_id=uuid.uuid4(),
        raw_text="DO-178C Rev B",
        normalized_key="do 178c rev b",
        doc_id_guess="DO-178C",
        title_guess=None,
        version_guess="B",
        clause_guess=None,
        publisher_guess=None,
        supplement_guess=None,
        locator={},
        extraction_method="test",
        resolution_state="pending",
        structured={},
    )
    base.update(kwargs)
    return ExtractedReference(**base)


def _entry(key, ver, **kwargs):
    sid = kwargs.get("standard_id", uuid.uuid4())
    svid = kwargs.get("standard_version_id", uuid.uuid4())
    return {
        "standard_id": sid,
        "standard_version_id": svid,
        "canonical_key": key,
        "canonical_key_norm": key.upper().replace(" ", "-"),
        "title": kwargs.get("title", "Software Considerations"),
        "title_norm": kwargs.get("title_norm", "software considerations"),
        "publisher": kwargs.get("publisher", "RTCA"),
        "publisher_norm": kwargs.get("publisher_norm", "RTCA"),
        "version_label": ver,
        "version_norm": ver.upper(),
        "supplement": kwargs.get("supplement"),
        "supplement_norm": (str(kwargs["supplement"]).upper() if kwargs.get("supplement") else None),
        "document_version_id": None,
        "aliases": kwargs.get("aliases", []),
    }


def test_auto_select_id_revision():
    e = _entry("DO-178C", "B")
    d = match_reference(_ref(), [e], approved_version_ids={e["standard_version_id"]})
    assert d.auto_selected is not None
    assert d.resolution_state == "auto_selected"
    assert d.auto_selected.match_method == "id_revision"


def test_never_auto_select_by_semantic_alone():
    ref = _ref(doc_id_guess=None, version_guess=None, raw_text="airborne software guidance")
    sem = [
        CatalogCandidate(
            standard_id=uuid.uuid4(),
            standard_version_id=uuid.uuid4(),
            canonical_key="DO-178C",
            title="x",
            publisher="RTCA",
            version_label="B",
            document_version_id=None,
            match_method="semantic_candidate",
            score=0.99,
        )
    ]
    d = match_reference(ref, catalog=[], approved_version_ids=set(), semantic_candidates=sem)
    assert d.auto_selected is None
    assert d.resolution_state == "needs_user"
    assert d.status_hint == ReferenceStatus.AMBIGUOUS_MATCH


def test_unspecified_revision_asks_user_never_latest():
    e1 = _entry("DO-178C", "A")
    e2 = _entry("DO-178C", "B", standard_id=e1["standard_id"])
    approved = {e1["standard_version_id"], e2["standard_version_id"]}
    ref = _ref(version_guess=None, raw_text="DO-178C")
    d = match_reference(ref, [e1, e2], approved_version_ids=approved)
    assert d.auto_selected is None
    assert d.status_hint == ReferenceStatus.VERSION_UNSPECIFIED
    assert len(d.candidates) == 2


def test_missing_source():
    d = match_reference(_ref(), catalog=[], approved_version_ids=set())
    assert d.resolution_state == "missing_source"
    assert d.status_hint == ReferenceStatus.MISSING_SOURCE
