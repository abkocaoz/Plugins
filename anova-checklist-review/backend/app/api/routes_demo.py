"""No-Docker / Try Live demo bootstrap (deterministic path without Qdrant/Ollama)."""

from __future__ import annotations

import time
import uuid
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_dev_token
from app.core.config import Settings, get_settings
from app.core.job_types import JobType
from app.db.session import get_db
from app.models.entities import (
    Document,
    DocumentVersion,
    Job,
    Project,
    ProjectStandardSet,
    StandardAlias,
    StandardCatalog,
    StandardVersion,
)
from app.services.checklist_catalog import seed_all_seedable, seed_catalog_by_key
from app.services.jobs import enqueue_job, make_idempotency_key
from app.services.normalize import normalize_doc_id
from app.services.storage import write_original

router = APIRouter(prefix="/api/v1/demo", tags=["demo"], dependencies=[Depends(require_dev_token)])

FIXTURES = Path(__file__).resolve().parents[1] / "demo_fixtures"


@router.get("/status")
async def demo_status(settings: Settings = Depends(get_settings)) -> dict[str, Any]:
    return {
        "demo_mode": settings.demo_mode,
        "worker_enabled": settings.worker_enabled,
        "auth_mode": settings.auth_mode,
        "fixtures_dir": str(FIXTURES),
        "fixtures": [p.name for p in FIXTURES.glob("*") if p.is_file()],
        "notes": [
            "demo_mode skips Qdrant/embedding upserts but continues extract→references→checklist",
            "document_content LLM items may ERROR without Ollama — deterministic items still run",
            "No production Excel templates invented; synthetic fixtures only",
        ],
    }


@router.post("/bootstrap")
async def demo_bootstrap(
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    """Seed catalogs + create a project with sample code + DO-178C stub standard."""
    seeded = await seed_all_seedable(db)

    project = await db.scalar(select(Project).where(Project.slug == "live-demo"))
    if project is None:
        project = Project(
            id=uuid.uuid4(),
            slug="live-demo",
            name="Live Demo",
            description="No-Docker Try Live bootstrap project",
            settings={"demo": True},
        )
        db.add(project)
        await db.flush()

    std = await db.scalar(
        select(StandardCatalog).where(StandardCatalog.canonical_key == "DO-178C")
    )
    if std is None:
        std = StandardCatalog(
            id=uuid.uuid4(),
            canonical_key="DO-178C",
            title="Software Considerations in Airborne Systems (demo stub)",
            publisher="RTCA",
            meta={"demo_stub": True},
        )
        db.add(std)
        await db.flush()

    std_ver = await db.scalar(
        select(StandardVersion).where(
            StandardVersion.standard_id == std.id,
            StandardVersion.version_label == "2011-demo",
        )
    )
    if std_ver is None:
        std_ver = StandardVersion(
            id=uuid.uuid4(),
            standard_id=std.id,
            version_label="2011-demo",
            publication_year=2011,
            meta={"demo_stub": True},
        )
        db.add(std_ver)
        await db.flush()

    rev = f"demo-{int(time.time())}"
    code_path = FIXTURES / "sample_module.c"
    std_path = FIXTURES / "do178c_stub.txt"

    code_doc, code_ver, code_job = await _upload_bytes(
        db,
        settings,
        project=project,
        title="Demo Flight Module",
        doc_type="code",
        version_label=rev,
        filename=code_path.name,
        data=code_path.read_bytes(),
        mime="text/x-c",
        extra_meta={"demo_fixture": "sample_module.c"},
    )
    std_doc, std_doc_ver, std_job = await _upload_bytes(
        db,
        settings,
        project=project,
        title="DO-178C demo stub",
        doc_type="standard",
        version_label=rev,
        filename=std_path.name,
        data=std_path.read_bytes(),
        mime="text/plain",
        extra_meta={
            "demo_fixture": "do178c_stub.txt",
            "standard_version_id": str(std_ver.id),
            "expected_doc_id": "DO-178C",
        },
        standard_version_id=std_ver.id,
    )
    std_ver.document_version_id = std_doc_ver.id

    # Pin DO-178C stub on the project so reference matching has an approved version.
    pss = await db.scalar(
        select(ProjectStandardSet).where(
            ProjectStandardSet.project_id == project.id,
            ProjectStandardSet.standard_version_id == std_ver.id,
        )
    )
    if pss is None:
        db.add(
            ProjectStandardSet(
                id=uuid.uuid4(),
                project_id=project.id,
                standard_version_id=std_ver.id,
                is_required=True,
                notes="Demo-approved coding standard",
            )
        )

    for alias in ("DO-178C", "DO178C"):
        norm = normalize_doc_id(alias)
        exists = await db.scalar(
            select(StandardAlias).where(
                StandardAlias.standard_id == std.id,
                StandardAlias.alias_normalized == norm,
            )
        )
        if exists is None:
            db.add(
                StandardAlias(
                    id=uuid.uuid4(),
                    standard_id=std.id,
                    alias=alias,
                    alias_normalized=norm,
                )
            )

    await seed_catalog_by_key(db, "software_code_standard", replace_items=False)
    await seed_catalog_by_key(db, "data_icd", replace_items=False)
    await seed_catalog_by_key(db, "seci", replace_items=False)

    await db.commit()

    return {
        "demo_mode": settings.demo_mode,
        "seeded_catalogs": seeded,
        "project_id": str(project.id),
        "project_slug": project.slug,
        "api_token": settings.dev_api_token if settings.auth_mode == "dev" else None,
        "code_document_id": str(code_doc.id),
        "code_document_version_id": str(code_ver.id),
        "standard_document_id": str(std_doc.id),
        "standard_document_version_id": str(std_doc_ver.id),
        "standard_version_id": str(std_ver.id),
        "extract_job_ids": [str(code_job.id), str(std_job.id)],
        "next_steps": [
            "Wait ~10–20s for extract → (degraded) index → reference jobs",
            "Open /ui/references with code_document_version_id",
            "Open /ui/checklist → start software_code_standard on that version",
            "document_content items may show ERROR without Ollama; deterministic items should complete",
        ],
        "ui": {
            "upload": "/ui",
            "references": "/ui/references",
            "checklist": "/ui/checklist",
        },
    }


async def _upload_bytes(
    db: AsyncSession,
    settings: Settings,
    *,
    project: Project,
    title: str,
    doc_type: str,
    version_label: str,
    filename: str,
    data: bytes,
    mime: str,
    extra_meta: dict[str, Any] | None = None,
    standard_version_id: uuid.UUID | None = None,
) -> tuple[Document, DocumentVersion, Job]:
    document = await db.scalar(
        select(Document).where(Document.project_id == project.id, Document.title == title)
    )
    if document is None:
        document = Document(
            id=uuid.uuid4(),
            project_id=project.id,
            title=title,
            doc_type=doc_type,
            meta={"demo": True},
        )
        db.add(document)
        await db.flush()

    version = DocumentVersion(
        id=uuid.uuid4(),
        document_id=document.id,
        version_label=version_label,
        storage_path="",
        content_sha256="",
        mime_type=mime,
        byte_size=len(data),
        parse_status="pending",
        meta={
            "original_filename": filename,
            "standard_version_id": str(standard_version_id) if standard_version_id else None,
            **(extra_meta or {}),
        },
    )
    db.add(version)
    await db.flush()

    dest, digest = write_original(
        Path(settings.upload_dir),
        project.id,
        document.id,
        version.id,
        filename,
        data,
    )
    version.storage_path = str(dest)
    version.content_sha256 = digest
    document.current_version_id = version.id
    document.doc_type = doc_type

    job = await enqueue_job(
        db,
        job_type=JobType.EXTRACT_DOCUMENT,
        payload={"document_version_id": str(version.id)},
        project_id=project.id,
        idempotency_key=make_idempotency_key(
            JobType.EXTRACT_DOCUMENT, version.id, digest, "demo-bootstrap"
        ),
    )
    return document, version, job
