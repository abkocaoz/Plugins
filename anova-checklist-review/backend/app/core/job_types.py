from __future__ import annotations

from enum import StrEnum


class JobType(StrEnum):
    EXTRACT_DOCUMENT = "extract_document"
    INDEX_DOCUMENT = "index_document"
    INDEX_STANDARD = "index_standard"
    REINDEX_PROJECT = "reindex_project"
    REFERENCE_RESOLUTION = "reference_resolution"
    REFERENCE_VALIDATION = "reference_validation"
    CHECKLIST_REVIEW = "checklist_review"
