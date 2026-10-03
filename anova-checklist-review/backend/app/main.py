from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import HTMLResponse

from app import __version__
from app.api.routes_documents import router as documents_router
from app.api.routes_health import router as health_router
from app.api.routes_jobs import router as jobs_router
from app.api.routes_projects import router as projects_router
from app.api.routes_standards import router as standards_router
from app.core.config import get_settings
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
    description="Document review + Excel checklist engine (Phase 2: upload/extract/index)",
    lifespan=lifespan,
)

app.include_router(health_router)
app.include_router(projects_router)
app.include_router(documents_router)
app.include_router(standards_router)
app.include_router(jobs_router)


@app.get("/ui", response_class=HTMLResponse, include_in_schema=False)
async def minimal_upload_ui() -> str:
    """Minimal hook to exercise upload → extract → index without a full SPA."""
    return """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8"/>
  <title>ACR Phase 2 — upload hook</title>
  <style>
    body{font-family:ui-sans-serif,system-ui,sans-serif;max-width:720px;margin:2rem auto;padding:0 1rem;line-height:1.45}
    label{display:block;margin-top:.75rem;font-weight:600}
    input,select,button{margin-top:.25rem;width:100%;padding:.5rem}
    button{cursor:pointer}
    pre{background:#f4f4f4;padding:1rem;overflow:auto}
  </style>
</head>
<body>
  <h1>Anova Checklist Review — Phase 2</h1>
  <p>Minimal upload hook. Create a project via API first, then upload here.</p>
  <label>API token <input id="token" value="dev-change-me"/></label>
  <label>Project ID <input id="projectId" placeholder="uuid"/></label>
  <label>Title <input id="title" placeholder="optional"/></label>
  <label>Doc type
    <select id="docType">
      <option value="source">source</option>
      <option value="standard">standard</option>
      <option value="code">code</option>
    </select>
  </label>
  <label>Revision / version label <input id="version" value="1"/></label>
  <label>Standard version ID (for standards) <input id="stdVer" placeholder="optional uuid"/></label>
  <label>File <input id="file" type="file"/></label>
  <button id="go">Upload</button>
  <h2>Response</h2>
  <pre id="out">{}</pre>
  <script>
  document.getElementById('go').onclick = async () => {
    const fd = new FormData();
    const f = document.getElementById('file').files[0];
    if (!f) { alert('choose a file'); return; }
    fd.append('file', f);
    const title = document.getElementById('title').value;
    if (title) fd.append('title', title);
    fd.append('doc_type', document.getElementById('docType').value);
    fd.append('version_label', document.getElementById('version').value);
    const std = document.getElementById('stdVer').value;
    if (std) fd.append('standard_version_id', std);
    const pid = document.getElementById('projectId').value.trim();
    const token = document.getElementById('token').value.trim();
    const r = await fetch('/api/v1/projects/' + pid + '/documents', {
      method: 'POST',
      headers: {'X-API-Token': token},
      body: fd
    });
    const text = await r.text();
    try { document.getElementById('out').textContent = JSON.stringify(JSON.parse(text), null, 2); }
    catch { document.getElementById('out').textContent = text; }
  };
  </script>
</body>
</html>"""
