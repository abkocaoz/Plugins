from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import HTMLResponse

from app import __version__
from app.api.routes_checklists import router as checklists_router
from app.api.routes_documents import router as documents_router
from app.api.routes_health import router as health_router
from app.api.routes_jobs import router as jobs_router
from app.api.routes_projects import router as projects_router
from app.api.routes_references import router as references_router
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
    description="Document review + Excel checklist engine (Phase 6: DataICD + SECI cross-doc)",
    lifespan=lifespan,
)

app.include_router(health_router)
app.include_router(projects_router)
app.include_router(documents_router)
app.include_router(standards_router)
app.include_router(jobs_router)
app.include_router(references_router)
app.include_router(checklists_router)


@app.get("/ui", response_class=HTMLResponse, include_in_schema=False)
async def minimal_upload_ui() -> str:
    return _UI_HTML


@app.get("/ui/references", response_class=HTMLResponse, include_in_schema=False)
async def reference_review_ui() -> str:
    return _REF_UI_HTML


@app.get("/ui/checklist", response_class=HTMLResponse, include_in_schema=False)
async def checklist_ui() -> str:
    return _CHECKLIST_UI_HTML


_UI_HTML = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8"/>
  <title>ACR Phase 4 — upload hook</title>
  <style>
    body{font-family:ui-sans-serif,system-ui,sans-serif;max-width:720px;margin:2rem auto;padding:0 1rem;line-height:1.45}
    label{display:block;margin-top:.75rem;font-weight:600}
    input,select,button{margin-top:.25rem;width:100%;padding:.5rem}
    button{cursor:pointer}
    pre{background:#f4f4f4;padding:1rem;overflow:auto}
    a{color:#0b5}
  </style>
</head>
<body>
  <h1>Anova Checklist Review — Phase 4</h1>
  <p>Upload → extract → index → references → <strong>Software Code Standard checklist</strong>.
  <a href="/ui/references">Reference review</a> · <a href="/ui/checklist">Checklist results</a></p>
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
  <label>Expected doc id (missing-source verify) <input id="expId" placeholder="e.g. DO-178C"/></label>
  <label>Fills missing reference id <input id="missRef" placeholder="optional extracted_reference uuid"/></label>
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
    const exp = document.getElementById('expId').value;
    if (exp) fd.append('expected_doc_id', exp);
    const miss = document.getElementById('missRef').value;
    if (miss) fd.append('fills_missing_reference_id', miss);
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


_REF_UI_HTML = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8"/>
  <title>ACR — Reference review</title>
  <style>
    body{font-family:ui-sans-serif,system-ui,sans-serif;max-width:960px;margin:2rem auto;padding:0 1rem;line-height:1.4}
    label{display:block;margin-top:.6rem;font-weight:600}
    input,button{margin-top:.25rem;padding:.5rem}
    input{width:100%}
    button{cursor:pointer}
    .card{border:1px solid #ddd;padding:0.75rem 1rem;margin:0.75rem 0;border-radius:6px}
    .status{font-weight:700}
    pre{background:#f6f6f6;padding:.5rem;overflow:auto;white-space:pre-wrap}
    .muted{color:#666;font-size:.9rem}
  </style>
</head>
<body>
  <h1>Reference review</h1>
  <p class="muted">Runs <em>before</em> checklist evaluation. Missing refs do not block independent checklist items.
  Selected standard versions are pinned on the review run.</p>
  <p><a href="/ui">← Upload</a></p>
  <label>API token <input id="token" value="dev-change-me"/></label>
  <label>Document version ID <input id="vid" placeholder="uuid"/></label>
  <button id="load">Load review</button>
  <button id="missing">List missing</button>
  <h2>Summary</h2>
  <pre id="sum">{}</pre>
  <h2>Items</h2>
  <div id="items"></div>
  <script>
  const token = () => document.getElementById('token').value.trim();
  const vid = () => document.getElementById('vid').value.trim();
  document.getElementById('load').onclick = async () => {
    const r = await fetch('/api/v1/document-versions/' + vid() + '/reference-review', {
      headers: {'X-API-Token': token()}
    });
    const data = await r.json();
    document.getElementById('sum').textContent = JSON.stringify({
      review_id: data.review_id,
      status: data.status,
      pinned_standard_version_ids: data.pinned_standard_version_ids,
      blocks_independent_checklist: data.blocks_independent_checklist,
      summary: data.summary
    }, null, 2);
    const root = document.getElementById('items');
    root.innerHTML = '';
    (data.items || []).forEach(it => {
      const d = document.createElement('div');
      d.className = 'card';
      d.innerHTML = '<div class="status">' + (it.finding && it.finding.status) +
        ' · ' + (it.finding && it.finding.check_type) + '</div>' +
        '<div>' + (it.finding && it.finding.message) + '</div>' +
        '<div class="muted">' + (it.reference && it.reference.raw_text) +
        ' @ ' + JSON.stringify(it.reference && it.reference.locator) + '</div>' +
        '<pre>' + JSON.stringify(it.finding && it.finding.details, null, 2) + '</pre>';
      root.appendChild(d);
    });
  };
  document.getElementById('missing').onclick = async () => {
    const r = await fetch('/api/v1/document-versions/' + vid() + '/missing-references', {
      headers: {'X-API-Token': token()}
    });
    document.getElementById('sum').textContent = JSON.stringify(await r.json(), null, 2);
  };
  </script>
</body>
</html>"""


_CHECKLIST_UI_HTML = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8"/>
  <title>ACR — Checklist review</title>
  <style>
    body{font-family:ui-sans-serif,system-ui,sans-serif;max-width:980px;margin:2rem auto;padding:0 1rem;line-height:1.4}
    label{display:block;margin-top:.6rem;font-weight:600}
    input,select,textarea,button{margin-top:.25rem;padding:.5rem}
    input,select,textarea{width:100%;box-sizing:border-box}
    button{cursor:pointer;margin-right:.5rem;margin-top:.5rem}
    .card{border:1px solid #ddd;padding:.75rem 1rem;margin:.75rem 0;border-radius:6px}
    .status{font-weight:700}
    pre{background:#f6f6f6;padding:.5rem;overflow:auto;white-space:pre-wrap}
    .muted{color:#666;font-size:.9rem}
    .row{display:flex;gap:.5rem;flex-wrap:wrap;align-items:flex-end}
    .row label{flex:1;min-width:140px}
  </style>
</head>
<body>
  <h1>Software Code Standard — human review</h1>
  <p class="muted">AI proposal is stored separately from reviewer_decisions / human_decision. Excel export fills a template copy (synthetic fixture until production templates are supplied).</p>
  <p><a href="/ui">← Upload</a> · <a href="/ui/references">References</a></p>
  <label>API token <input id="token" value="dev-change-me"/></label>
  <label>Project ID <input id="pid"/></label>
  <label>Document version ID <input id="vid"/></label>
  <label>Definition key
    <select id="dkey">
      <option value="software_code_standard">software_code_standard</option>
      <option value="data_icd">data_icd</option>
      <option value="seci">seci</option>
    </select>
  </label>
  <label>Pinned peer document version IDs (comma-separated, for SECI) <input id="peers"/></label>
  <label>Checklist run ID <input id="rid"/></label>
  <button id="seed">Seed selected catalog</button>
  <button id="start">Start checklist_review job</button>
  <button id="load">Load run view</button>
  <button id="exportDraft">Export draft</button>
  <button id="exportApproved">Export reviewer-approved</button>
  <button id="listExports">List exports</button>
  <h2>Output</h2>
  <pre id="out">{}</pre>
  <div id="items"></div>
  <script>
  const token = () => document.getElementById('token').value.trim();
  const headers = () => ({'X-API-Token': token(), 'Content-Type': 'application/json'});
  document.getElementById('seed').onclick = async () => {
    const key = document.getElementById('dkey').value.replaceAll('_','-');
    const r = await fetch('/api/v1/checklists/seed/' + key, {method:'POST', headers: headers()});
    document.getElementById('out').textContent = JSON.stringify(await r.json(), null, 2);
  };
  document.getElementById('start').onclick = async () => {
    const pid = document.getElementById('pid').value.trim();
    const peers = document.getElementById('peers').value.split(',').map(s => s.trim()).filter(Boolean);
    const body = {
      document_version_id: document.getElementById('vid').value.trim(),
      definition_key: document.getElementById('dkey').value,
      pinned_document_version_ids: peers
    };
    const r = await fetch('/api/v1/projects/' + pid + '/checklist-runs', {
      method:'POST', headers: headers(), body: JSON.stringify(body)
    });
    document.getElementById('out').textContent = JSON.stringify(await r.json(), null, 2);
  };
  async function startExport(mode) {
    const rid = document.getElementById('rid').value.trim();
    const r = await fetch('/api/v1/checklist-runs/' + rid + '/export', {
      method:'POST', headers: headers(), body: JSON.stringify({mode})
    });
    document.getElementById('out').textContent = JSON.stringify(await r.json(), null, 2);
  }
  document.getElementById('exportDraft').onclick = () => startExport('draft');
  document.getElementById('exportApproved').onclick = () => startExport('reviewer_approved');
  document.getElementById('listExports').onclick = async () => {
    const rid = document.getElementById('rid').value.trim();
    const r = await fetch('/api/v1/checklist-runs/' + rid + '/exports', {headers: {'X-API-Token': token()}});
    const data = await r.json();
    document.getElementById('out').textContent = JSON.stringify(data, null, 2);
  };
  document.getElementById('load').onclick = async () => {
    const rid = document.getElementById('rid').value.trim();
    const r = await fetch('/api/v1/checklist-runs/' + rid + '/view', {headers: {'X-API-Token': token()}});
    const data = await r.json();
    document.getElementById('out').textContent = JSON.stringify({
      run: data.run, template_gap: data.template_gap,
      excel_template_ready: data.excel_template_ready,
      pinned_standard_version_ids: data.pinned_standard_version_ids
    }, null, 2);
    const root = document.getElementById('items');
    root.innerHTML = '';
    (data.items || []).forEach(it => {
      const d = document.createElement('div');
      d.className = 'card';
      d.dataset.answerId = it.answer_id;
      d.innerHTML =
        '<div class="status">' + it.state +
        (it.human_decision ? ' · human=' + it.human_decision : ' · human=∅') +
        ' · ' + it.method + '</div>' +
        '<div><strong>' + it.item_key + '</strong> — ' + it.question + '</div>' +
        '<div class="muted">' + (it.rationale || '') + '</div>' +
        '<pre>ai_proposal: ' + JSON.stringify(it.ai_proposal, null, 2) + '</pre>' +
        '<details><summary>Evidence (' + (it.evidence||[]).length + ')</summary><pre>' +
          JSON.stringify(it.evidence, null, 2) + '</pre></details>' +
        '<details><summary>Related reference findings (' +
          (it.related_reference_findings||[]).length + ')</summary><pre>' +
          JSON.stringify(it.related_reference_findings, null, 2) + '</pre></details>' +
        '<div class="row">' +
          '<label>Decision<select class="dec">' +
            '<option value="accept">accept AI</option>' +
            '<option value="override">override</option>' +
            '<option value="reject">reject</option>' +
            '<option value="defer">defer</option>' +
          '</select></label>' +
          '<label>Override state<select class="ost">' +
            '<option value="">(none)</option>' +
            '<option>YES</option><option>NO</option><option>NA</option>' +
            '<option>INSUFFICIENT_EVIDENCE</option><option>MANUAL_REVIEW</option><option>ERROR</option>' +
          '</select></label>' +
          '<label>Status cell<input class="stv" placeholder="optional; not auto-Closed"/></label>' +
        '</div>' +
        '<label>Change rationale<textarea class="rat" rows="2"></textarea></label>' +
        '<button class="save">Save human decision</button>' +
        '<pre class="decOut muted"></pre>';
      d.querySelector('.save').onclick = async () => {
        const body = {
          decision: d.querySelector('.dec').value,
          override_state: d.querySelector('.ost').value || null,
          change_rationale: d.querySelector('.rat').value || null,
          status_value: d.querySelector('.stv').value || null,
          reviewed_item: 'Yes'
        };
        const resp = await fetch('/api/v1/checklist-answers/' + it.answer_id + '/decision', {
          method:'POST', headers: headers(), body: JSON.stringify(body)
        });
        d.querySelector('.decOut').textContent = JSON.stringify(await resp.json(), null, 2);
      };
      root.appendChild(d);
    });
  };
  </script>
</body>
</html>"""
