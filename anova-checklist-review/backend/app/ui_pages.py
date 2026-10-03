"""Server-rendered HTML for the simplified /ui flow (Turkish labels OK)."""

from __future__ import annotations

_SHARED_CSS = """
:root{
  --ink:#142033;--muted:#5a6578;--line:#d8dee8;--bg:#f3f5f8;--card:#fff;
  --accent:#1f6b5a;--accent-ink:#fff;--warn:#8a5a12;--err:#a33;
}
*{box-sizing:border-box}
body{font-family:"Segoe UI",ui-sans-serif,system-ui,sans-serif;margin:0;background:var(--bg);color:var(--ink);line-height:1.45}
.wrap{max-width:720px;margin:0 auto;padding:1.5rem 1rem 3rem}
h1{font-size:1.55rem;margin:0 0 .35rem}
.lead{color:var(--muted);margin:0 0 1.25rem}
.nav{font-size:.92rem;margin-bottom:1rem}
.nav a{color:var(--accent);margin-right:.75rem}
.panel{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:1rem 1.1rem;margin:0 0 1rem}
.panel h2{font-size:1.05rem;margin:0 0 .75rem}
label{display:block;font-weight:600;margin-top:.7rem;font-size:.92rem}
input,select,button,textarea{margin-top:.3rem;width:100%;padding:.55rem .65rem;border:1px solid var(--line);border-radius:8px;font:inherit}
button{cursor:pointer;background:#eef1f5}
button.primary{background:var(--accent);color:var(--accent-ink);border-color:var(--accent);font-weight:700;padding:.7rem}
button.primary:disabled{opacity:.55;cursor:not-allowed}
button.secondary{background:#fff}
.row{display:flex;gap:.6rem;flex-wrap:wrap;align-items:flex-end}
.row>*{flex:1;min-width:140px}
.muted{color:var(--muted);font-size:.88rem}
.status{margin-top:.85rem;padding:.65rem .75rem;border-radius:8px;background:#eef6f3;border:1px solid #cfe3dc}
.status.err{background:#fceeee;border-color:#f0c4c4;color:var(--err)}
.status.warn{background:#fff7e8;border-color:#f0d9a8;color:var(--warn)}
.ctx{font-size:.9rem;background:#eef2f7;border:1px solid var(--line);border-radius:8px;padding:.65rem .8rem;margin-bottom:1rem}
details.adv{margin-top:1rem;color:var(--muted)}
details.adv summary{cursor:pointer;font-weight:600}
pre{background:#f6f7fa;padding:.65rem;overflow:auto;white-space:pre-wrap;border-radius:6px;font-size:.82rem}
.card{border:1px solid var(--line);padding:.75rem 1rem;margin:.75rem 0;border-radius:8px;background:#fff}
.tabs{display:flex;gap:.4rem;margin:.4rem 0 .8rem}
.tabs button{width:auto;flex:1}
.tabs button.active{background:var(--accent);color:#fff;border-color:var(--accent);font-weight:700}
.hide{display:none}
"""

_SESSION_JS = """
const SESSION_KEY = 'acr_session';
const LEGACY_DEMO_KEY = 'acr_live_demo';
const DEFAULT_TOKEN = 'dev-change-me';

function loadSession() {
  try {
    const s = JSON.parse(localStorage.getItem(SESSION_KEY) || 'null');
    if (s) return s;
  } catch {}
  try {
    const d = JSON.parse(localStorage.getItem(LEGACY_DEMO_KEY) || 'null');
    if (!d) return null;
    return {
      api_token: d.api_token || DEFAULT_TOKEN,
      project_id: d.project_id || null,
      document_version_id: d.code_document_version_id || null,
      document_title: null,
      definition_key: 'software_code_standard',
      definition_title: 'Software Code Standard',
      checklist_job_id: null,
      checklist_run_id: null
    };
  } catch { return null; }
}
function saveSession(patch) {
  const cur = loadSession() || {};
  const next = Object.assign({}, cur, patch || {});
  if (!next.api_token) next.api_token = DEFAULT_TOKEN;
  localStorage.setItem(SESSION_KEY, JSON.stringify(next));
  return next;
}
function token() {
  const s = loadSession();
  return (s && s.api_token) || DEFAULT_TOKEN;
}
function authHeaders(json) {
  const h = {'X-API-Token': token()};
  if (json) h['Content-Type'] = 'application/json';
  return h;
}
function qs(name) {
  return new URLSearchParams(location.search).get(name);
}
function setStatus(el, msg, kind) {
  if (!el) return;
  el.className = 'status' + (kind ? ' ' + kind : '');
  el.textContent = msg || '';
  el.classList.toggle('hide', !msg);
}
async function pollJob(jobId, onTick, maxAttempts) {
  const n = maxAttempts || 40;
  for (let i = 0; i < n; i++) {
    const r = await fetch('/api/v1/jobs/' + jobId, {headers: authHeaders()});
    const job = await r.json();
    if (onTick) onTick(job);
    if (job.status === 'succeeded' || job.status === 'failed') return job;
    await new Promise(res => setTimeout(res, 1000));
  }
  return null;
}
"""

HOME_HTML = f"""<!doctype html>
<html lang="tr">
<head>
  <meta charset="utf-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1"/>
  <title>Anova Checklist — Başlat</title>
  <style>{_SHARED_CSS}</style>
</head>
<body>
  <div class="wrap">
    <h1>Anova Checklist Review</h1>
    <p class="lead">Doküman ve checklist seçin, <strong>Başlat</strong> ile incelemeyi çalıştırın.</p>
    <div class="nav">
      <a href="/ui">Ana sayfa</a>
      <a href="/ui/references">Referanslar</a>
      <a href="/ui/checklist">Checklist</a>
    </div>

    <div class="panel">
      <h2>1. Doküman</h2>
      <div class="tabs">
        <button type="button" id="tabExisting" class="active">Mevcut revizyon</button>
        <button type="button" id="tabUpload">Yeni yükle</button>
      </div>
      <div id="existingPane">
        <label>Revizyon
          <select id="revisionSelect"><option value="">Yükleniyor…</option></select>
        </label>
        <p class="muted" id="revisionHint"></p>
      </div>
      <div id="uploadPane" class="hide">
        <label>Dosya <input id="file" type="file"/></label>
        <label>Başlık (isteğe bağlı) <input id="title" placeholder="Dosya adından türetilir"/></label>
        <label>Tür
          <select id="docType">
            <option value="code">code</option>
            <option value="source">source</option>
            <option value="standard">standard</option>
          </select>
        </label>
        <label>Revizyon etiketi <input id="versionLabel" value="1"/></label>
      </div>
    </div>

    <div class="panel">
      <h2>2. Checklist</h2>
      <label>Tanım
        <select id="checklistSelect"><option value="">Yükleniyor…</option></select>
      </label>
      <p class="muted" id="checklistHint">Mevcut registry katalogları (sentetik şablonlar).</p>
    </div>

    <button class="primary" id="startBtn" type="button">Başlat</button>
    <div id="status" class="status hide"></div>

    <details class="adv">
      <summary>Gelişmiş / örnek veri</summary>
      <p class="muted">Boş listede örnek proje için bootstrap kullanın. Token demo ortamında otomatik.</p>
      <button class="secondary" id="bootstrapBtn" type="button">Örnek veri yükle (Live Demo)</button>
      <pre id="advOut">{{}}</pre>
    </details>
  </div>
  <script>
  {_SESSION_JS}
  let home = null;
  let mode = 'existing';

  function setMode(m) {{
    mode = m;
    document.getElementById('tabExisting').classList.toggle('active', m === 'existing');
    document.getElementById('tabUpload').classList.toggle('active', m === 'upload');
    document.getElementById('existingPane').classList.toggle('hide', m !== 'existing');
    document.getElementById('uploadPane').classList.toggle('hide', m !== 'upload');
  }}
  document.getElementById('tabExisting').onclick = () => setMode('existing');
  document.getElementById('tabUpload').onclick = () => setMode('upload');

  async function refreshHome(preferVid) {{
    const st = document.getElementById('status');
    setStatus(st, 'Yükleniyor…');
    const r = await fetch('/api/v1/ui/home', {{headers: authHeaders()}});
    home = await r.json();
    if (!r.ok) {{
      setStatus(st, 'Ana ekran verisi alınamadı', 'err');
      document.getElementById('advOut').textContent = JSON.stringify(home, null, 2);
      return;
    }}
    if (home.api_token_hint) saveSession({{api_token: home.api_token_hint}});
    if (home.project) saveSession({{project_id: home.project.id}});

    const sel = document.getElementById('revisionSelect');
    const revs = home.document_revisions || [];
    sel.innerHTML = '';
    if (!revs.length) {{
      sel.innerHTML = '<option value="">(doküman yok)</option>';
      document.getElementById('revisionHint').textContent = home.empty_hint || '';
      setMode('upload');
    }} else {{
      const session = loadSession() || {{}};
      const pick = preferVid || qs('vid') || session.document_version_id;
      revs.forEach(rev => {{
        const opt = document.createElement('option');
        opt.value = rev.version_id;
        const cur = rev.is_current ? ' · güncel' : '';
        opt.textContent = rev.title + ' — ' + rev.version_label + ' (' + rev.doc_type + ', ' + rev.parse_status + ')' + cur;
        if (pick && pick === rev.version_id) opt.selected = true;
        sel.appendChild(opt);
      }});
      document.getElementById('revisionHint').textContent = home.project
        ? ('Proje: ' + home.project.name)
        : '';
    }}

    const csel = document.getElementById('checklistSelect');
    csel.innerHTML = '';
    const lists = home.checklists || [];
    const want = qs('dkey') || (loadSession() || {{}}).definition_key || 'software_code_standard';
    lists.forEach(c => {{
      const opt = document.createElement('option');
      opt.value = c.definition_key;
      opt.textContent = c.title + (c.status ? ' — ' + c.status : '');
      if (c.definition_key === want) opt.selected = true;
      csel.appendChild(opt);
    }});
    setStatus(st, '');
    document.getElementById('advOut').textContent = JSON.stringify({{
      project: home.project,
      revision_count: revs.length,
      checklists: lists.map(c => c.definition_key)
    }}, null, 2);
  }}

  document.getElementById('bootstrapBtn').onclick = async () => {{
    const st = document.getElementById('status');
    setStatus(st, 'Örnek veri yükleniyor…');
    const r = await fetch('/api/v1/demo/bootstrap', {{method:'POST', headers: authHeaders()}});
    const data = await r.json();
    document.getElementById('advOut').textContent = JSON.stringify(data, null, 2);
    if (!r.ok) {{ setStatus(st, 'Bootstrap başarısız', 'err'); return; }}
    saveSession({{
      api_token: data.api_token || token(),
      project_id: data.project_id,
      document_version_id: data.code_document_version_id,
      document_title: 'Demo Flight Module',
      definition_key: 'software_code_standard'
    }});
    localStorage.setItem(LEGACY_DEMO_KEY, JSON.stringify(data));
    setStatus(st, 'Örnek veri hazır. Extract için ~15 sn bekleyip Başlat diyebilirsiniz.', 'warn');
    await refreshHome(data.code_document_version_id);
    setMode('existing');
  }};

  document.getElementById('startBtn').onclick = async () => {{
    const st = document.getElementById('status');
    const btn = document.getElementById('startBtn');
    btn.disabled = true;
    try {{
      if (!home || !home.project) {{
        setStatus(st, 'Önce örnek veri yükleyin veya proje oluşturun.', 'err');
        return;
      }}
      const definition_key = document.getElementById('checklistSelect').value;
      if (!definition_key) {{ setStatus(st, 'Checklist seçin', 'err'); return; }}
      let versionId = null;
      let projectId = home.project.id;

      if (mode === 'upload') {{
        const f = document.getElementById('file').files[0];
        if (!f) {{ setStatus(st, 'Dosya seçin', 'err'); return; }}
        setStatus(st, 'Yükleniyor…');
        const fd = new FormData();
        fd.append('file', f);
        const title = document.getElementById('title').value.trim();
        if (title) fd.append('title', title);
        fd.append('doc_type', document.getElementById('docType').value);
        fd.append('version_label', document.getElementById('versionLabel').value || '1');
        const up = await fetch('/api/v1/projects/' + projectId + '/documents', {{
          method:'POST', headers: {{'X-API-Token': token()}}, body: fd
        }});
        const uploaded = await up.json();
        document.getElementById('advOut').textContent = JSON.stringify(uploaded, null, 2);
        if (!up.ok) {{ setStatus(st, 'Yükleme başarısız', 'err'); return; }}
        versionId = uploaded.version && uploaded.version.id;
        setStatus(st, 'Extract bekleniyor…', 'warn');
        // brief wait so extract can start
        for (let i = 0; i < 20; i++) {{
          await new Promise(res => setTimeout(res, 1000));
          const vr = await fetch('/api/v1/document-versions/' + versionId, {{headers: authHeaders()}});
          const ver = await vr.json();
          if (ver.parse_status && ver.parse_status !== 'pending') break;
        }}
      }} else {{
        versionId = document.getElementById('revisionSelect').value;
        if (!versionId) {{ setStatus(st, 'Revizyon seçin', 'err'); return; }}
      }}

      setStatus(st, 'İnceleme başlatılıyor…');
      const sr = await fetch('/api/v1/ui/start-review', {{
        method:'POST',
        headers: authHeaders(true),
        body: JSON.stringify({{
          project_id: projectId,
          document_version_id: versionId,
          definition_key
        }})
      }});
      const started = await sr.json();
      document.getElementById('advOut').textContent = JSON.stringify(started, null, 2);
      if (!sr.ok) {{
        setStatus(st, (started && started.detail) ? JSON.stringify(started.detail) : 'Başlatma başarısız', 'err');
        return;
      }}
      saveSession(Object.assign({{}}, started.session || {{}}, {{api_token: token()}}));

      setStatus(st, 'Checklist job çalışıyor…', 'warn');
      const job = await pollJob(started.checklist_job_id, j => {{
        setStatus(st, 'Checklist: ' + j.status + (j.last_error ? ' — ' + j.last_error : ''), j.status === 'failed' ? 'err' : 'warn');
      }});
      const rid = job && job.result && job.result.checklist_run_id;
      if (rid) saveSession({{checklist_run_id: rid}});
      if (job && job.status === 'succeeded' && rid) {{
        location.href = '/ui/checklist?pid=' + encodeURIComponent(projectId) +
          '&vid=' + encodeURIComponent(versionId) +
          '&dkey=' + encodeURIComponent(definition_key) +
          '&rid=' + encodeURIComponent(rid);
        return;
      }}
      // fallback: open checklist page with job context
      location.href = started.next.checklist;
    }} catch (e) {{
      setStatus(st, String(e), 'err');
    }} finally {{
      btn.disabled = false;
    }}
  }};

  refreshHome();
  </script>
</body>
</html>"""

REF_HTML = f"""<!doctype html>
<html lang="tr">
<head>
  <meta charset="utf-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1"/>
  <title>ACR — Referanslar</title>
  <style>{_SHARED_CSS}</style>
</head>
<body>
  <div class="wrap">
    <h1>Referans incelemesi</h1>
    <p class="lead">Checklist’ten önce referans doğrulama özeti. Bağlam ana sayfadan gelir.</p>
    <div class="nav">
      <a href="/ui">← Ana sayfa</a>
      <a href="/ui/checklist">Checklist</a>
    </div>
    <div class="ctx" id="ctx">Bağlam yükleniyor…</div>
    <button class="primary" id="load" type="button">İncelemeyi yükle</button>
    <button class="secondary" id="missing" type="button">Eksik referanslar</button>
    <div id="status" class="status hide"></div>
    <h2>Özet</h2>
    <pre id="sum">{{}}</pre>
    <h2>Maddeler</h2>
    <div id="items"></div>
    <details class="adv"><summary>Teknik kimlikler</summary>
      <label>Document version ID <input id="vid"/></label>
      <pre id="adv"></pre>
    </details>
  </div>
  <script>
  {_SESSION_JS}
  (function init() {{
    const s = loadSession() || {{}};
    const vid = qs('vid') || s.document_version_id || '';
    document.getElementById('vid').value = vid;
    if (qs('pid')) saveSession({{project_id: qs('pid')}});
    if (vid) saveSession({{document_version_id: vid}});
    const title = s.document_title || 'seçili doküman';
    document.getElementById('ctx').textContent = vid
      ? ('Doküman: ' + title + ' · revizyon bağlamı hazır')
      : 'Bağlam yok — ana sayfadan Başlat ile gelin.';
    document.getElementById('adv').textContent = JSON.stringify({{vid, session: s}}, null, 2);
    if (vid) document.getElementById('load').click();
  }})();
  const vid = () => document.getElementById('vid').value.trim();
  document.getElementById('load').onclick = async () => {{
    const st = document.getElementById('status');
    if (!vid()) {{ setStatus(st, 'Doküman versiyonu yok', 'err'); return; }}
    setStatus(st, 'Yükleniyor…');
    const r = await fetch('/api/v1/document-versions/' + vid() + '/reference-review', {{
      headers: authHeaders()
    }});
    const data = await r.json();
    if (!r.ok) {{ setStatus(st, 'Yükleme başarısız', 'err'); document.getElementById('sum').textContent = JSON.stringify(data, null, 2); return; }}
    setStatus(st, 'Durum: ' + (data.status || 'ok'));
    document.getElementById('sum').textContent = JSON.stringify({{
      review_id: data.review_id,
      status: data.status,
      pinned_standard_version_ids: data.pinned_standard_version_ids,
      blocks_independent_checklist: data.blocks_independent_checklist,
      summary: data.summary
    }}, null, 2);
    const root = document.getElementById('items');
    root.innerHTML = '';
    (data.items || []).forEach(it => {{
      const d = document.createElement('div');
      d.className = 'card';
      d.innerHTML = '<div><strong>' + (it.finding && it.finding.status) +
        '</strong> · ' + (it.finding && it.finding.check_type) + '</div>' +
        '<div>' + (it.finding && it.finding.message) + '</div>' +
        '<div class="muted">' + (it.reference && it.reference.raw_text) + '</div>';
      root.appendChild(d);
    }});
  }};
  document.getElementById('missing').onclick = async () => {{
    const r = await fetch('/api/v1/document-versions/' + vid() + '/missing-references', {{
      headers: authHeaders()
    }});
    document.getElementById('sum').textContent = JSON.stringify(await r.json(), null, 2);
  }};
  </script>
</body>
</html>"""

CHECKLIST_HTML = f"""<!doctype html>
<html lang="tr">
<head>
  <meta charset="utf-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1"/>
  <title>ACR — Checklist</title>
  <style>{_SHARED_CSS}</style>
</head>
<body>
  <div class="wrap" style="max-width:980px">
    <h1>Checklist sonuçları</h1>
    <p class="lead">İnsan kararı ve export. Bağlam ana sayfa / Başlat akışından gelir.</p>
    <div class="nav">
      <a href="/ui">← Ana sayfa</a>
      <a href="/ui/references">Referanslar</a>
    </div>
    <div class="ctx" id="ctx">Bağlam yükleniyor…</div>
    <div class="row">
      <button class="primary" id="load" type="button">Sonuçları yükle</button>
      <button class="secondary" id="exportDraft" type="button">Export (taslak)</button>
      <button class="secondary" id="exportApproved" type="button">Export (onaylı)</button>
    </div>
    <div id="status" class="status hide"></div>
    <pre id="out">{{}}</pre>
    <div id="items"></div>
    <details class="adv"><summary>Teknik kimlikler / manuel job</summary>
      <label>Project ID <input id="pid"/></label>
      <label>Document version ID <input id="vid"/></label>
      <label>Definition key <input id="dkey"/></label>
      <label>Checklist run ID <input id="rid"/></label>
      <label>Job ID <input id="job"/></label>
      <button id="waitJob" type="button">Job’u bekle ve run ID al</button>
    </details>
  </div>
  <script>
  {_SESSION_JS}
  (function init() {{
    const s = loadSession() || {{}};
    const pid = qs('pid') || s.project_id || '';
    const vid = qs('vid') || s.document_version_id || '';
    const dkey = qs('dkey') || s.definition_key || 'software_code_standard';
    const rid = qs('rid') || s.checklist_run_id || '';
    const job = qs('job') || s.checklist_job_id || '';
    document.getElementById('pid').value = pid;
    document.getElementById('vid').value = vid;
    document.getElementById('dkey').value = dkey;
    document.getElementById('rid').value = rid;
    document.getElementById('job').value = job;
    saveSession({{project_id: pid || null, document_version_id: vid || null, definition_key: dkey, checklist_run_id: rid || null, checklist_job_id: job || null}});
    const title = s.document_title || 'doküman';
    const defTitle = s.definition_title || dkey;
    document.getElementById('ctx').textContent = (pid && vid)
      ? (title + ' · ' + defTitle + (rid ? ' · run hazır' : (job ? ' · job bekleniyor' : '')))
      : 'Bağlam eksik — ana sayfadan Başlat ile gelin.';
    if (rid) document.getElementById('load').click();
    else if (job) document.getElementById('waitJob').click();
  }})();

  document.getElementById('waitJob').onclick = async () => {{
    const st = document.getElementById('status');
    const jobId = document.getElementById('job').value.trim();
    if (!jobId) {{ setStatus(st, 'Job ID yok', 'err'); return; }}
    setStatus(st, 'Job bekleniyor…', 'warn');
    const job = await pollJob(jobId, j => setStatus(st, 'Job: ' + j.status, j.status === 'failed' ? 'err' : 'warn'));
    document.getElementById('out').textContent = JSON.stringify(job, null, 2);
    const rid = job && job.result && job.result.checklist_run_id;
    if (rid) {{
      document.getElementById('rid').value = rid;
      saveSession({{checklist_run_id: rid}});
      document.getElementById('load').click();
    }}
  }};

  document.getElementById('load').onclick = async () => {{
    const st = document.getElementById('status');
    const rid = document.getElementById('rid').value.trim();
    if (!rid) {{ setStatus(st, 'Henüz run ID yok — job bitmesini bekleyin', 'warn'); return; }}
    const r = await fetch('/api/v1/checklist-runs/' + rid + '/view', {{headers: authHeaders()}});
    const data = await r.json();
    if (!r.ok) {{ setStatus(st, 'Yükleme başarısız', 'err'); document.getElementById('out').textContent = JSON.stringify(data, null, 2); return; }}
    setStatus(st, 'Run: ' + (data.run && data.run.status));
    document.getElementById('out').textContent = JSON.stringify({{
      run: data.run, template_gap: data.template_gap,
      excel_template_ready: data.excel_template_ready
    }}, null, 2);
    const root = document.getElementById('items');
    root.innerHTML = '';
    (data.items || []).forEach(it => {{
      const d = document.createElement('div');
      d.className = 'card';
      d.innerHTML =
        '<div><strong>' + it.item_key + '</strong> — ' + it.state +
        (it.human_decision ? ' · human=' + it.human_decision : '') + '</div>' +
        '<div>' + it.question + '</div>' +
        '<div class="muted">' + (it.rationale || '') + '</div>' +
        '<div class="row">' +
          '<label>Karar<select class="dec">' +
            '<option value="accept">AI kabul</option>' +
            '<option value="override">override</option>' +
            '<option value="reject">reject</option>' +
            '<option value="defer">defer</option>' +
          '</select></label>' +
          '<label>Override<select class="ost"><option value="">(yok)</option>' +
            '<option>YES</option><option>NO</option><option>NA</option>' +
            '<option>INSUFFICIENT_EVIDENCE</option><option>MANUAL_REVIEW</option><option>ERROR</option>' +
          '</select></label>' +
        '</div>' +
        '<label>Gerekçe<textarea class="rat" rows="2"></textarea></label>' +
        '<button class="save" type="button">Kaydet</button>' +
        '<pre class="decOut muted"></pre>';
      d.querySelector('.save').onclick = async () => {{
        const body = {{
          decision: d.querySelector('.dec').value,
          override_state: d.querySelector('.ost').value || null,
          change_rationale: d.querySelector('.rat').value || null,
          reviewed_item: 'Yes'
        }};
        const resp = await fetch('/api/v1/checklist-answers/' + it.answer_id + '/decision', {{
          method:'POST', headers: authHeaders(true), body: JSON.stringify(body)
        }});
        d.querySelector('.decOut').textContent = JSON.stringify(await resp.json(), null, 2);
      }};
      root.appendChild(d);
    }});
  }};

  async function startExport(mode) {{
    const rid = document.getElementById('rid').value.trim();
    const r = await fetch('/api/v1/checklist-runs/' + rid + '/export', {{
      method:'POST', headers: authHeaders(true), body: JSON.stringify({{mode}})
    }});
    document.getElementById('out').textContent = JSON.stringify(await r.json(), null, 2);
  }}
  document.getElementById('exportDraft').onclick = () => startExport('draft');
  document.getElementById('exportApproved').onclick = () => startExport('reviewer_approved');
  </script>
</body>
</html>"""
