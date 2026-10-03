from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import HTMLResponse

from app import __version__
from app.api.routes_checklists import router as checklists_router
from app.api.routes_demo import router as demo_router
from app.api.routes_documents import router as documents_router
from app.api.routes_health import router as health_router
from app.api.routes_jobs import router as jobs_router
from app.api.routes_projects import router as projects_router
from app.api.routes_references import router as references_router
from app.api.routes_standards import router as standards_router
from app.api.routes_ui import router as ui_router
from app.core.config import get_settings
from app.ui_pages import CHECKLIST_HTML, HOME_HTML, REF_HTML
from app.workers.runner import worker_loop

settings = get_settings()
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    Path(settings.upload_dir).mkdir(parents=True, exist_ok=True)
    Path(settings.export_dir).mkdir(parents=True, exist_ok=True)
    stop_event = asyncio.Event()
    worker_task: asyncio.Task | None = None
    if settings.worker_enabled:
        worker_task = asyncio.create_task(worker_loop(settings, stop_event))
        logger.info("background job worker enabled")
    yield
    stop_event.set()
    if worker_task is not None:
        worker_task.cancel()
        try:
            await worker_task
        except asyncio.CancelledError:
            pass


app = FastAPI(
    title=settings.app_name,
    version=__version__,
    description="Document review + Excel checklist engine (Phases 1–7: registry + ops docs)",
    lifespan=lifespan,
)

app.include_router(health_router)
app.include_router(projects_router)
app.include_router(documents_router)
app.include_router(standards_router)
app.include_router(jobs_router)
app.include_router(references_router)
app.include_router(checklists_router)
app.include_router(demo_router)
app.include_router(ui_router)


@app.get("/ui", response_class=HTMLResponse, include_in_schema=False)
async def minimal_upload_ui() -> str:
    return HOME_HTML


@app.get("/ui/references", response_class=HTMLResponse, include_in_schema=False)
async def reference_review_ui() -> str:
    return REF_HTML


@app.get("/ui/checklist", response_class=HTMLResponse, include_in_schema=False)
async def checklist_ui() -> str:
    return CHECKLIST_HTML
