"""PostgreSQL job queue with leases, heartbeat, and idempotency keys."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Sequence

from sqlalchemy import Select, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import JobStatus
from app.core.job_types import JobType
from app.models.entities import Job


def make_idempotency_key(job_type: str, *parts: object) -> str:
    return ":".join([job_type, *[str(p) for p in parts]])


async def enqueue_job(
    session: AsyncSession,
    *,
    job_type: JobType | str,
    payload: dict[str, Any],
    project_id: uuid.UUID | None = None,
    idempotency_key: str | None = None,
    max_attempts: int = 3,
) -> Job:
    jt = str(job_type)
    if idempotency_key:
        existing = await session.scalar(
            select(Job).where(Job.idempotency_key == idempotency_key)
        )
        if existing is not None:
            # Idempotent: if still active or succeeded, return existing.
            if existing.status in {
                JobStatus.QUEUED,
                JobStatus.LEASED,
                JobStatus.RUNNING,
                JobStatus.SUCCEEDED,
            }:
                return existing
            # Failed/cancelled: requeue in place
            existing.status = JobStatus.QUEUED
            existing.payload = payload
            existing.result = {}
            existing.last_error = None
            existing.lease_owner = None
            existing.lease_expires_at = None
            existing.available_at = datetime.now(timezone.utc)
            existing.attempts = 0
            existing.max_attempts = max_attempts
            await session.flush()
            return existing

    job = Job(
        id=uuid.uuid4(),
        project_id=project_id,
        job_type=jt,
        status=JobStatus.QUEUED,
        payload=payload,
        result={},
        attempts=0,
        max_attempts=max_attempts,
        idempotency_key=idempotency_key,
        available_at=datetime.now(timezone.utc),
    )
    session.add(job)
    await session.flush()
    return job


async def claim_next_job(
    session: AsyncSession,
    *,
    owner: str,
    lease_seconds: int,
    job_types: Sequence[str] | None = None,
) -> Job | None:
    """Claim one available job using SKIP LOCKED."""
    now = datetime.now(timezone.utc)
    lease_until = now + timedelta(seconds=lease_seconds)
    type_filter = ""
    params: dict[str, Any] = {
        "owner": owner,
        "now": now,
        "lease_until": lease_until,
        "leased": JobStatus.LEASED,
        "queued": JobStatus.QUEUED,
        "running": JobStatus.RUNNING,
    }
    if job_types:
        type_filter = "AND job_type = ANY(:job_types)"
        params["job_types"] = list(job_types)

    sql = text(
        f"""
        WITH candidate AS (
            SELECT id FROM jobs
            WHERE (
                (status = :queued AND available_at <= :now)
                OR (
                    status IN (:leased, :running)
                    AND lease_expires_at IS NOT NULL
                    AND lease_expires_at < :now
                )
            )
            {type_filter}
            ORDER BY available_at ASC
            FOR UPDATE SKIP LOCKED
            LIMIT 1
        )
        UPDATE jobs AS j
        SET status = :leased,
            lease_owner = :owner,
            lease_expires_at = :lease_until,
            attempts = j.attempts + 1,
            updated_at = :now
        FROM candidate
        WHERE j.id = candidate.id
        RETURNING j.id
        """
    )
    result = await session.execute(sql, params)
    row = result.first()
    if not row:
        return None
    job_id = row[0]
    job = await session.get(Job, job_id)
    return job


async def heartbeat_job(
    session: AsyncSession, job_id: uuid.UUID, owner: str, lease_seconds: int
) -> bool:
    now = datetime.now(timezone.utc)
    lease_until = now + timedelta(seconds=lease_seconds)
    res = await session.execute(
        update(Job)
        .where(Job.id == job_id, Job.lease_owner == owner)
        .values(
            status=JobStatus.RUNNING,
            lease_expires_at=lease_until,
            updated_at=now,
        )
    )
    return bool(res.rowcount)


async def complete_job(
    session: AsyncSession,
    job: Job,
    *,
    result: dict[str, Any] | None = None,
) -> None:
    job.status = JobStatus.SUCCEEDED
    job.result = result or {}
    job.lease_owner = None
    job.lease_expires_at = None
    job.last_error = None
    job.updated_at = datetime.now(timezone.utc)


async def fail_job(session: AsyncSession, job: Job, error: str, *, requeue: bool = True) -> None:
    now = datetime.now(timezone.utc)
    job.last_error = error[:4000]
    job.lease_owner = None
    job.lease_expires_at = None
    job.updated_at = now
    if requeue and job.attempts < job.max_attempts:
        job.status = JobStatus.QUEUED
        job.available_at = now + timedelta(seconds=min(60, 5 * job.attempts))
    else:
        job.status = JobStatus.FAILED


def jobs_select(project_id: uuid.UUID | None = None, limit: int = 50) -> Select[tuple[Job]]:
    stmt = select(Job).order_by(Job.created_at.desc()).limit(limit)
    if project_id is not None:
        stmt = stmt.where(Job.project_id == project_id)
    return stmt
