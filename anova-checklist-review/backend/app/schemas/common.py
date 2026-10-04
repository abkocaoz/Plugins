from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class ProjectCreate(BaseModel):
    slug: str = Field(min_length=1, max_length=120)
    name: str = Field(min_length=1, max_length=200)
    description: str | None = None


class ProjectOut(ORMModel):
    id: uuid.UUID
    slug: str
    name: str
    description: str | None
    settings: dict[str, Any]
    created_at: datetime


class DocumentOut(ORMModel):
    id: uuid.UUID
    project_id: uuid.UUID
    title: str
    doc_type: str
    current_version_id: uuid.UUID | None
    meta: dict[str, Any]
    created_at: datetime


class DocumentVersionOut(ORMModel):
    id: uuid.UUID
    document_id: uuid.UUID
    version_label: str
    storage_path: str
    content_sha256: str
    mime_type: str | None
    byte_size: int
    parse_status: str
    extracted_text_path: str | None
    meta: dict[str, Any]
    created_at: datetime


class UploadResponse(BaseModel):
    document: DocumentOut
    version: DocumentVersionOut
    extract_job_id: uuid.UUID


class StandardCreate(BaseModel):
    canonical_key: str = Field(min_length=1, max_length=200)
    title: str = Field(min_length=1, max_length=500)
    publisher: str | None = None
    meta: dict[str, Any] = Field(default_factory=dict)


class StandardOut(ORMModel):
    id: uuid.UUID
    canonical_key: str
    title: str
    publisher: str | None
    meta: dict[str, Any]
    created_at: datetime


class StandardVersionCreate(BaseModel):
    version_label: str = Field(min_length=1, max_length=120)
    publication_year: int | None = None
    meta: dict[str, Any] = Field(default_factory=dict)


class StandardVersionOut(ORMModel):
    id: uuid.UUID
    standard_id: uuid.UUID
    version_label: str
    publication_year: int | None
    document_version_id: uuid.UUID | None
    meta: dict[str, Any]
    created_at: datetime


class AliasCreate(BaseModel):
    alias: str = Field(min_length=1, max_length=300)


class AliasOut(ORMModel):
    id: uuid.UUID
    standard_id: uuid.UUID
    alias: str
    alias_normalized: str
    created_at: datetime


class JobOut(ORMModel):
    id: uuid.UUID
    project_id: uuid.UUID | None
    job_type: str
    status: str
    payload: dict[str, Any]
    result: dict[str, Any]
    attempts: int
    max_attempts: int
    last_error: str | None
    idempotency_key: str | None
    created_at: datetime
    updated_at: datetime


class ProjectStandardSetCreate(BaseModel):
    standard_version_id: uuid.UUID
    is_required: bool = True
    notes: str | None = None
