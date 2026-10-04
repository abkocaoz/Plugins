"""Shared enums for reference validation and checklist answers."""

from __future__ import annotations

from enum import StrEnum


class ReferenceStatus(StrEnum):
    VERIFIED = "VERIFIED"
    METADATA_MISMATCH = "METADATA_MISMATCH"
    VERSION_UNSPECIFIED = "VERSION_UNSPECIFIED"
    VERSION_MISMATCH = "VERSION_MISMATCH"
    CLAUSE_NOT_FOUND = "CLAUSE_NOT_FOUND"
    CLAIM_NOT_SUPPORTED = "CLAIM_NOT_SUPPORTED"
    MISSING_SOURCE = "MISSING_SOURCE"
    AMBIGUOUS_MATCH = "AMBIGUOUS_MATCH"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"
    MANUAL_REVIEW = "MANUAL_REVIEW"


class ChecklistAnswerState(StrEnum):
    """Phase 4 answer states (Software Code Standard engine)."""

    YES = "YES"
    NO = "NO"
    NA = "NA"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"
    MANUAL_REVIEW = "MANUAL_REVIEW"
    ERROR = "ERROR"
    PENDING = "PENDING"


class ChecklistMethod(StrEnum):
    DOCUMENT_CONTENT = "document_content"
    DETERMINISTIC_RULE = "deterministic_rule"
    CROSS_DOCUMENT = "cross_document"
    TRACEABILITY = "traceability"
    EXTERNAL_EVIDENCE = "external_evidence"
    MANUAL_REVIEW = "manual_review"


class JobStatus(StrEnum):
    QUEUED = "queued"
    LEASED = "leased"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


class MembershipRole(StrEnum):
    OWNER = "owner"
    REVIEWER = "reviewer"
    VIEWER = "viewer"
