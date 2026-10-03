from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_dev_token
from app.db.session import get_db
from app.models.entities import Project
from app.schemas.common import ProjectCreate, ProjectOut

router = APIRouter(prefix="/api/v1/projects", tags=["projects"], dependencies=[Depends(require_dev_token)])


@router.post("", response_model=ProjectOut, status_code=status.HTTP_201_CREATED)
async def create_project(body: ProjectCreate, db: AsyncSession = Depends(get_db)) -> Project:
    existing = await db.scalar(select(Project).where(Project.slug == body.slug))
    if existing:
        raise HTTPException(status_code=409, detail="slug already exists")
    project = Project(
        id=uuid.uuid4(),
        slug=body.slug,
        name=body.name,
        description=body.description,
        settings={},
    )
    db.add(project)
    await db.commit()
    await db.refresh(project)
    return project


@router.get("", response_model=list[ProjectOut])
async def list_projects(db: AsyncSession = Depends(get_db)) -> list[Project]:
    rows = (await db.scalars(select(Project).order_by(Project.created_at.desc()))).all()
    return list(rows)


@router.get("/{project_id}", response_model=ProjectOut)
async def get_project(project_id: uuid.UUID, db: AsyncSession = Depends(get_db)) -> Project:
    project = await db.get(Project, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="project not found")
    return project
