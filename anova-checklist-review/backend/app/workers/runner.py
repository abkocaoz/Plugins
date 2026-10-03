"""In-process background worker: claim → heartbeat → process extract/index jobs."""

from __future__ import annotations

import asyncio
import logging
import os
import socket
import uuid

from app.core.config import Settings, get_settings
from app.core.job_types import JobType
from app.db.session import SessionLocal
from app.models.entities import Job
from app.services.jobs import claim_next_job, complete_job, fail_job, heartbeat_job
from app.services.pipeline import process_job

logger = logging.getLogger(__name__)

WORKER_JOB_TYPES = [
    JobType.EXTRACT_DOCUMENT.value,
    JobType.INDEX_DOCUMENT.value,
    JobType.INDEX_STANDARD.value,
    JobType.REINDEX_PROJECT.value,
    JobType.REFERENCE_RESOLUTION.value,
    JobType.REFERENCE_VALIDATION.value,
    JobType.CHECKLIST_REVIEW.value,
]


def worker_owner_id() -> str:
    return f"{socket.gethostname()}:{os.getpid()}:{uuid.uuid4().hex[:8]}"


async def worker_loop(
    settings: Settings | None = None, stop_event: asyncio.Event | None = None
) -> None:
    settings = settings or get_settings()
    owner = worker_owner_id()
    stop_event = stop_event or asyncio.Event()
    logger.info("job worker started owner=%s", owner)

    while not stop_event.is_set():
        try:
            claimed = await _claim_and_run(settings, owner)
            if not claimed:
                try:
                    await asyncio.wait_for(stop_event.wait(), timeout=settings.worker_poll_seconds)
                except asyncio.TimeoutError:
                    pass
        except Exception:  # noqa: BLE001
            logger.exception("worker loop error")
            await asyncio.sleep(settings.worker_poll_seconds)

    logger.info("job worker stopped owner=%s", owner)


async def _claim_and_run(settings: Settings, owner: str) -> bool:
    async with SessionLocal() as session:
        job = await claim_next_job(
            session,
            owner=owner,
            lease_seconds=settings.worker_lease_seconds,
            job_types=WORKER_JOB_TYPES,
        )
        if job is None:
            await session.commit()
            return False
        job_id = job.id
        await session.commit()

    stop_hb = asyncio.Event()

    async def _hb() -> None:
        while not stop_hb.is_set():
            try:
                await asyncio.wait_for(stop_hb.wait(), timeout=settings.worker_heartbeat_seconds)
            except asyncio.TimeoutError:
                async with SessionLocal() as session:
                    await heartbeat_job(session, job_id, owner, settings.worker_lease_seconds)
                    await session.commit()

    hb_task = asyncio.create_task(_hb())
    try:
        async with SessionLocal() as session:
            job = await session.get(Job, job_id)
            if job is None:
                return True
            await heartbeat_job(session, job_id, owner, settings.worker_lease_seconds)
            try:
                result = await process_job(session, settings, job)
                await complete_job(session, job, result=result)
                await session.commit()
                logger.info("job %s (%s) succeeded", job_id, job.job_type)
            except Exception as exc:  # noqa: BLE001
                logger.exception("job %s failed", job_id)
                await fail_job(session, job, str(exc), requeue=True)
                await session.commit()
    finally:
        stop_hb.set()
        hb_task.cancel()
        try:
            await hb_task
        except asyncio.CancelledError:
            pass
    return True
