from __future__ import annotations

import uuid

from app.services.qdrant_index import (
    DENSE_VECTOR_NAME,
    PROJECT_DOC_PAYLOAD_INDEXES,
    SPARSE_VECTOR_NAME,
    STANDARD_PAYLOAD_INDEXES,
    point_id_for,
)


def test_point_id_deterministic():
    vid = uuid.uuid4()
    assert point_id_for("proj", vid, 0) == point_id_for("proj", vid, 0)
    assert point_id_for("proj", vid, 0) != point_id_for("proj", vid, 1)


def test_required_payload_indexes_present():
    proj_fields = {name for name, _ in PROJECT_DOC_PAYLOAD_INDEXES}
    std_fields = {name for name, _ in STANDARD_PAYLOAD_INDEXES}
    assert {
        "project_id",
        "document_id",
        "document_version_id",
        "content_sha256",
        "chunk_index",
    } <= proj_fields
    assert {
        "standard_id",
        "standard_version_id",
        "canonical_key",
        "chunk_index",
    } <= std_fields
    assert DENSE_VECTOR_NAME == "dense"
    assert SPARSE_VECTOR_NAME == "sparse"
