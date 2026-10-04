from __future__ import annotations

from app.core.job_types import JobType
from app.services.jobs import make_idempotency_key


def test_idempotency_key_stable():
    a = make_idempotency_key(JobType.EXTRACT_DOCUMENT, "vid", "sha")
    b = make_idempotency_key(JobType.EXTRACT_DOCUMENT, "vid", "sha")
    c = make_idempotency_key(JobType.INDEX_DOCUMENT, "vid", "sha")
    assert a == b
    assert a != c
    assert a.startswith("extract_document:")
