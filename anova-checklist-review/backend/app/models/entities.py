from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Optional

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


def _uuid() -> uuid.UUID:
    return uuid.uuid4()


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class User(Base, TimestampMixin):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    email: Mapped[str] = mapped_column(String(320), unique=True, nullable=False)
    display_name: Mapped[str] = mapped_column(String(200), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    hashed_password: Mapped[Optional[str]] = mapped_column(String(255))

    memberships: Mapped[list[Membership]] = relationship(back_populates="user")


class Project(Base, TimestampMixin):
    __tablename__ = "projects"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    slug: Mapped[str] = mapped_column(String(120), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text)
    settings: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)

    memberships: Mapped[list[Membership]] = relationship(back_populates="project")
    documents: Mapped[list[Document]] = relationship(back_populates="project")


class Membership(Base, TimestampMixin):
    __tablename__ = "memberships"
    __table_args__ = (UniqueConstraint("project_id", "user_id", name="uq_membership_project_user"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    role: Mapped[str] = mapped_column(String(32), nullable=False, default="viewer")

    project: Mapped[Project] = relationship(back_populates="memberships")
    user: Mapped[User] = relationship(back_populates="memberships")


class Document(Base, TimestampMixin):
    __tablename__ = "documents"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    doc_type: Mapped[str] = mapped_column(String(64), nullable=False, default="source")
    # source | standard | code | checklist_input | other
    current_version_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True))
    meta: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)

    project: Mapped[Project] = relationship(back_populates="documents")
    versions: Mapped[list[DocumentVersion]] = relationship(back_populates="document")


class DocumentVersion(Base, TimestampMixin):
    __tablename__ = "document_versions"
    __table_args__ = (UniqueConstraint("document_id", "version_label", name="uq_doc_version_label"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True
    )
    version_label: Mapped[str] = mapped_column(String(120), nullable=False)
    storage_path: Mapped[str] = mapped_column(String(1024), nullable=False)
    content_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    mime_type: Mapped[Optional[str]] = mapped_column(String(128))
    byte_size: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    parse_status: Mapped[str] = mapped_column(String(32), default="pending", nullable=False)
    extracted_text_path: Mapped[Optional[str]] = mapped_column(String(1024))
    meta: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)

    document: Mapped[Document] = relationship(back_populates="versions")


class StandardCatalog(Base, TimestampMixin):
    __tablename__ = "standard_catalog"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    canonical_key: Mapped[str] = mapped_column(String(200), unique=True, nullable=False)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    publisher: Mapped[Optional[str]] = mapped_column(String(200))
    meta: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)

    versions: Mapped[list[StandardVersion]] = relationship(back_populates="standard")
    aliases: Mapped[list[StandardAlias]] = relationship(back_populates="standard")


class StandardVersion(Base, TimestampMixin):
    __tablename__ = "standard_versions"
    __table_args__ = (
        UniqueConstraint("standard_id", "version_label", name="uq_standard_version_label"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    standard_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("standard_catalog.id", ondelete="CASCADE"), nullable=False
    )
    version_label: Mapped[str] = mapped_column(String(120), nullable=False)
    publication_year: Mapped[Optional[int]] = mapped_column(Integer)
    document_version_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("document_versions.id", ondelete="SET NULL")
    )
    meta: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)

    standard: Mapped[StandardCatalog] = relationship(back_populates="versions")


class StandardAlias(Base, TimestampMixin):
    __tablename__ = "standard_aliases"
    __table_args__ = (UniqueConstraint("alias", name="uq_standard_alias"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    standard_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("standard_catalog.id", ondelete="CASCADE"), nullable=False
    )
    alias: Mapped[str] = mapped_column(String(300), nullable=False)
    alias_normalized: Mapped[str] = mapped_column(String(300), nullable=False, index=True)

    standard: Mapped[StandardCatalog] = relationship(back_populates="aliases")


class ProjectStandardSet(Base, TimestampMixin):
    __tablename__ = "project_standard_sets"
    __table_args__ = (
        UniqueConstraint("project_id", "standard_version_id", name="uq_project_standard_version"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    standard_version_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("standard_versions.id", ondelete="CASCADE"), nullable=False
    )
    is_required: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    notes: Mapped[Optional[str]] = mapped_column(Text)


class ExtractedReference(Base, TimestampMixin):
    __tablename__ = "extracted_references"
    __table_args__ = (Index("ix_extracted_refs_doc_version", "document_version_id"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    document_version_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("document_versions.id", ondelete="CASCADE"), nullable=False
    )
    raw_text: Mapped[str] = mapped_column(Text, nullable=False)
    normalized_key: Mapped[Optional[str]] = mapped_column(String(300), index=True)
    doc_id_guess: Mapped[Optional[str]] = mapped_column(String(200))
    title_guess: Mapped[Optional[str]] = mapped_column(String(500))
    version_guess: Mapped[Optional[str]] = mapped_column(String(120))
    clause_guess: Mapped[Optional[str]] = mapped_column(String(120))
    context_span: Mapped[Optional[str]] = mapped_column(Text)
    locator: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    extraction_method: Mapped[str] = mapped_column(String(64), default="regex", nullable=False)
    # Phase 3 structured fields — NULL when uncertain (never invented)
    publisher_guess: Mapped[Optional[str]] = mapped_column(String(200))
    supplement_guess: Mapped[Optional[str]] = mapped_column(String(120))
    date_guess: Mapped[Optional[str]] = mapped_column(String(32))
    section_kind: Mapped[Optional[str]] = mapped_column(String(64))
    normalization_version: Mapped[Optional[str]] = mapped_column(String(64))
    resolution_state: Mapped[str] = mapped_column(String(32), default="pending", nullable=False)
    # pending | auto_selected | needs_user | user_selected | missing_source
    selected_match_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True))
    structured: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)


class ReferenceMatch(Base, TimestampMixin):
    __tablename__ = "reference_matches"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    extracted_reference_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("extracted_references.id", ondelete="CASCADE"), nullable=False
    )
    standard_version_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("standard_versions.id", ondelete="SET NULL")
    )
    document_version_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("document_versions.id", ondelete="SET NULL")
    )
    score: Mapped[Optional[float]] = mapped_column(Float)
    rank: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    match_method: Mapped[str] = mapped_column(String(64), nullable=False, default="hybrid")
    meta: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)


class ReferenceFinding(Base, TimestampMixin):
    __tablename__ = "reference_findings"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    extracted_reference_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("extracted_references.id", ondelete="CASCADE"), nullable=False
    )
    reference_match_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("reference_matches.id", ondelete="SET NULL")
    )
    status: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    check_type: Mapped[str] = mapped_column(String(64), nullable=False)
    # bibliographic | consistency | clause | applicability | claim_support
    message: Mapped[str] = mapped_column(Text, nullable=False)
    details: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    blocks_dependent_items: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)


class ChecklistDefinition(Base, TimestampMixin):
    __tablename__ = "checklist_definitions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    key: Mapped[str] = mapped_column(String(120), unique=True, nullable=False)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text)
    version_label: Mapped[str] = mapped_column(String(64), nullable=False, default="1.0")
    excel_template_path: Mapped[Optional[str]] = mapped_column(String(1024))
    meta: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)

    items: Mapped[list[ChecklistItem]] = relationship(back_populates="definition")


class ChecklistItem(Base, TimestampMixin):
    __tablename__ = "checklist_items"
    __table_args__ = (
        UniqueConstraint("definition_id", "item_key", name="uq_checklist_item_key"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    definition_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("checklist_definitions.id", ondelete="CASCADE"), nullable=False
    )
    item_key: Mapped[str] = mapped_column(String(120), nullable=False)
    prompt: Mapped[str] = mapped_column(Text, nullable=False)
    method: Mapped[str] = mapped_column(String(64), nullable=False, default="llm_json")
    # rule | retrieval | llm_json | hybrid | human
    depends_on_references: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    excel_cell: Mapped[Optional[str]] = mapped_column(String(32))
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    schema_json: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)

    definition: Mapped[ChecklistDefinition] = relationship(back_populates="items")


class ChecklistRun(Base, TimestampMixin):
    __tablename__ = "checklist_runs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    definition_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("checklist_definitions.id", ondelete="RESTRICT"), nullable=False
    )
    document_version_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("document_versions.id", ondelete="RESTRICT"), nullable=False
    )
    status: Mapped[str] = mapped_column(String(32), default="pending", nullable=False)
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    meta: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)


class ChecklistAnswer(Base, TimestampMixin):
    __tablename__ = "checklist_answers"
    __table_args__ = (
        UniqueConstraint("run_id", "item_id", name="uq_checklist_answer_run_item"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("checklist_runs.id", ondelete="CASCADE"), nullable=False
    )
    item_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("checklist_items.id", ondelete="CASCADE"), nullable=False
    )
    # Effective display state (AI proposal until human decides in Phase 5)
    state: Mapped[str] = mapped_column(String(64), nullable=False, default="PENDING")
    confidence: Mapped[Optional[float]] = mapped_column(Float)
    rationale: Mapped[Optional[str]] = mapped_column(Text)
    raw_model_output: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    # Phase 4: keep AI proposal separate from human decision
    ai_proposal: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    human_decision: Mapped[Optional[str]] = mapped_column(String(64))
    chapter_text: Mapped[Optional[str]] = mapped_column(Text)
    comment_text: Mapped[Optional[str]] = mapped_column(Text)
    excel_answer_cell: Mapped[Optional[str]] = mapped_column(String(32))
    excel_chapter_cell: Mapped[Optional[str]] = mapped_column(String(32))
    excel_comment_cell: Mapped[Optional[str]] = mapped_column(String(32))


class Review(Base, TimestampMixin):
    __tablename__ = "reviews"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    checklist_run_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("checklist_runs.id", ondelete="SET NULL")
    )
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="open", nullable=False)
    created_by: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    # Phase 3: kind=reference_validation, pinned_standard_version_ids, document_version_id
    meta: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)


class ReviewItem(Base, TimestampMixin):
    __tablename__ = "review_items"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    review_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("reviews.id", ondelete="CASCADE"), nullable=False
    )
    checklist_answer_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("checklist_answers.id", ondelete="SET NULL")
    )
    reference_finding_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("reference_findings.id", ondelete="SET NULL")
    )
    status: Mapped[str] = mapped_column(String(32), default="open", nullable=False)
    notes: Mapped[Optional[str]] = mapped_column(Text)


class EvidenceLink(Base, TimestampMixin):
    __tablename__ = "evidence_links"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    checklist_answer_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("checklist_answers.id", ondelete="CASCADE")
    )
    reference_finding_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("reference_findings.id", ondelete="CASCADE")
    )
    document_version_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("document_versions.id", ondelete="SET NULL")
    )
    quote: Mapped[str] = mapped_column(Text, nullable=False)
    locator: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    qdrant_point_id: Mapped[Optional[str]] = mapped_column(String(128))


class ReviewerDecision(Base, TimestampMixin):
    __tablename__ = "reviewer_decisions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    review_item_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("review_items.id", ondelete="CASCADE"), nullable=False
    )
    reviewer_user_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    decision: Mapped[str] = mapped_column(String(64), nullable=False)
    # accept | reject | override | defer
    override_state: Mapped[Optional[str]] = mapped_column(String(64))
    comment: Mapped[Optional[str]] = mapped_column(Text)


class Job(Base, TimestampMixin):
    __tablename__ = "jobs"
    __table_args__ = (
        Index("ix_jobs_status_available", "status", "available_at"),
        Index("ix_jobs_lease", "lease_owner", "lease_expires_at"),
        UniqueConstraint("idempotency_key", name="uq_jobs_idempotency_key"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    project_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE")
    )
    job_type: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="queued", nullable=False, index=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    result: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    max_attempts: Mapped[int] = mapped_column(Integer, default=3, nullable=False)
    available_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    lease_owner: Mapped[Optional[str]] = mapped_column(String(128))
    lease_expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[Optional[str]] = mapped_column(Text)
    idempotency_key: Mapped[Optional[str]] = mapped_column(String(300))


class Export(Base, TimestampMixin):
    __tablename__ = "exports"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    checklist_run_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("checklist_runs.id", ondelete="SET NULL")
    )
    review_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("reviews.id", ondelete="SET NULL")
    )
    storage_path: Mapped[str] = mapped_column(String(1024), nullable=False)
    template_path: Mapped[Optional[str]] = mapped_column(String(1024))
    content_sha256: Mapped[Optional[str]] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(32), default="pending", nullable=False)
    meta: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)


class AuditEvent(Base, TimestampMixin):
    __tablename__ = "audit_events"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    project_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="SET NULL")
    )
    actor_user_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    action: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    entity_type: Mapped[str] = mapped_column(String(120), nullable=False)
    entity_id: Mapped[Optional[str]] = mapped_column(String(64))
    details: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
