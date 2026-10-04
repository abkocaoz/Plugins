from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_dev_token
from app.db.session import get_db
from app.models.entities import (
    Project,
    ProjectStandardSet,
    StandardAlias,
    StandardCatalog,
    StandardVersion,
)
from app.schemas.common import (
    AliasCreate,
    AliasOut,
    ProjectStandardSetCreate,
    StandardCreate,
    StandardOut,
    StandardVersionCreate,
    StandardVersionOut,
)
from app.services.normalize import normalize_alias

router = APIRouter(prefix="/api/v1", tags=["standards"], dependencies=[Depends(require_dev_token)])


@router.post("/standards", response_model=StandardOut, status_code=status.HTTP_201_CREATED)
async def create_standard(body: StandardCreate, db: AsyncSession = Depends(get_db)) -> StandardCatalog:
    existing = await db.scalar(
        select(StandardCatalog).where(StandardCatalog.canonical_key == body.canonical_key)
    )
    if existing:
        raise HTTPException(status_code=409, detail="canonical_key exists")
    row = StandardCatalog(
        id=uuid.uuid4(),
        canonical_key=body.canonical_key,
        title=body.title,
        publisher=body.publisher,
        meta=body.meta,
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return row


@router.get("/standards", response_model=list[StandardOut])
async def list_standards(db: AsyncSession = Depends(get_db)) -> list[StandardCatalog]:
    return list(await db.scalars(select(StandardCatalog).order_by(StandardCatalog.canonical_key)))


@router.get("/standards/{standard_id}", response_model=StandardOut)
async def get_standard(standard_id: uuid.UUID, db: AsyncSession = Depends(get_db)) -> StandardCatalog:
    row = await db.get(StandardCatalog, standard_id)
    if not row:
        raise HTTPException(status_code=404, detail="standard not found")
    return row


@router.post(
    "/standards/{standard_id}/versions",
    response_model=StandardVersionOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_standard_version(
    standard_id: uuid.UUID,
    body: StandardVersionCreate,
    db: AsyncSession = Depends(get_db),
) -> StandardVersion:
    standard = await db.get(StandardCatalog, standard_id)
    if not standard:
        raise HTTPException(status_code=404, detail="standard not found")
    clash = await db.scalar(
        select(StandardVersion).where(
            StandardVersion.standard_id == standard_id,
            StandardVersion.version_label == body.version_label,
        )
    )
    if clash:
        raise HTTPException(status_code=409, detail="version_label exists")
    row = StandardVersion(
        id=uuid.uuid4(),
        standard_id=standard_id,
        version_label=body.version_label,
        publication_year=body.publication_year,
        meta=body.meta,
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return row


@router.get(
    "/standards/{standard_id}/versions",
    response_model=list[StandardVersionOut],
)
async def list_standard_versions(
    standard_id: uuid.UUID, db: AsyncSession = Depends(get_db)
) -> list[StandardVersion]:
    return list(
        await db.scalars(
            select(StandardVersion)
            .where(StandardVersion.standard_id == standard_id)
            .order_by(StandardVersion.created_at.desc())
        )
    )


@router.post(
    "/standards/{standard_id}/aliases",
    response_model=AliasOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_alias(
    standard_id: uuid.UUID, body: AliasCreate, db: AsyncSession = Depends(get_db)
) -> StandardAlias:
    standard = await db.get(StandardCatalog, standard_id)
    if not standard:
        raise HTTPException(status_code=404, detail="standard not found")
    normalized = normalize_alias(body.alias)
    clash = await db.scalar(select(StandardAlias).where(StandardAlias.alias == body.alias))
    if clash:
        raise HTTPException(status_code=409, detail="alias exists")
    row = StandardAlias(
        id=uuid.uuid4(),
        standard_id=standard_id,
        alias=body.alias,
        alias_normalized=normalized,
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return row


@router.get("/standards/{standard_id}/aliases", response_model=list[AliasOut])
async def list_aliases(
    standard_id: uuid.UUID, db: AsyncSession = Depends(get_db)
) -> list[StandardAlias]:
    return list(
        await db.scalars(
            select(StandardAlias).where(StandardAlias.standard_id == standard_id)
        )
    )


@router.post(
    "/projects/{project_id}/standard-sets",
    status_code=status.HTTP_201_CREATED,
)
async def add_project_standard(
    project_id: uuid.UUID,
    body: ProjectStandardSetCreate,
    db: AsyncSession = Depends(get_db),
) -> dict:
    project = await db.get(Project, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="project not found")
    std_v = await db.get(StandardVersion, body.standard_version_id)
    if not std_v:
        raise HTTPException(status_code=404, detail="standard_version not found")
    row = ProjectStandardSet(
        id=uuid.uuid4(),
        project_id=project_id,
        standard_version_id=body.standard_version_id,
        is_required=body.is_required,
        notes=body.notes,
    )
    db.add(row)
    try:
        await db.commit()
    except Exception as exc:  # noqa: BLE001
        await db.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    await db.refresh(row)
    return {
        "id": str(row.id),
        "project_id": str(row.project_id),
        "standard_version_id": str(row.standard_version_id),
        "is_required": row.is_required,
    }
