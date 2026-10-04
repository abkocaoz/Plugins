from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_dev_token
from app.core.job_types import JobType
from app.db.session import get_db
from app.models.entities import Job, Project
from app.schemas.common import JobOut
from app.services.jobs import enqueue_job, jobs_select, make_idempotency_key

router = APIRouter(prefix="/api/v1", tags=["jobs"], dependencies=[Depends(require_dev_token)])


@router.get("/jobs/{job_id}", response_model=JobOut)
async def get_job(job_id: uuid.UUID, db: AsyncSession = Depends(get_db)) -> Job:
    job = await db.get(Job, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="job not found")
    return job


@router.get("/projects/{project_id}/jobs", response_model=list[JobOut])
async def list_project_jobs(
    project_id: uuid.UUID, db: AsyncSession = Depends(get_db)
) -> list[Job]:
    project = await db.get(Project, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="project not found")
    rows = (await db.scalars(jobs_select(project_id=project_id, limit=100))).all()
    return list(rows)


@router.post(
    "/projects/{project_id}/reindex",
    response_model=JobOut,
    status_code=status.HTTP_202_ACCEPTED,
)
async def reindex_project(
    project_id: uuid.UUID, db: AsyncSession = Depends(get_db)
) -> Job:
    project = await db.get(Project, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="project not found")
    job = await enqueue_job(
        db,
        job_type=JobType.REINDEX_PROJECT,
        payload={"project_id": str(project_id)},
        project_id=project_id,
        idempotency_key=make_idempotency_key(JobType.REINDEX_PROJECT, project_id, "manual"),
    )
    # Allow explicit re-trigger: if succeeded earlier, force requeue
    if job.status == "succeeded":
        job.status = "queued"
        job.result = {}
        job.last_error = None
    await db.commit()
    await db.refresh(job)
    return job
