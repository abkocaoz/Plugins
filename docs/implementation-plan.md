# Anova Checklist Review — Implementation Plan

**Project:** Reviewer / `anova-checklist-review`  
**Stack (v1):** FastAPI + PostgreSQL + Qdrant + BGE-M3 (separate embedding service) + Ollama + React/TypeScript  
**Compose project name:** `anova-checklist-review`  
**Status:** Phase 2 (upload → extract → index) implemented on branch; Phase 3+ not started

---

## 1. Repository findings (inspected)

| Finding | Detail |
|---|---|
| Repo root | Historically **iDangero.us jQuery plugins** (`Chop Slider 3`, `mOover`, `S6`, `Typewriter`). Not related to checklist review. |
| Closest existing app | `GereksinimKarsilastirma/` — Turkish **Streamlit** DOORS requirements comparison tool (CSV/Excel, optional Ollama `qwen2.5:3b`, openpyxl export, local JSON projects). |
| React / SPA frontend | **None** present for this product. Phase UI will be **new React + TypeScript**. |
| Excel checklist templates | **None** in repo (no `.xlsx` / `.xlsm`). Export must accept user-supplied templates; preserve sheets, formulas, styles, data validation, defined names. |
| Prior related planning | Branch `claude/traceability-matrix-planning-1azd0d` has `traceability-checker/PLAN.md` (SDD matrix checker). Conceptual cousin only; **not** this product’s data model. |
| Live SVN / DOORS | Out of scope for v1. Sources are **uploaded** PDF/DOCX/XLSX/CSV/code. |
| Language | Existing tooling is Turkish-facing; plan and UI copy may be bilingual (TR/EN). |

**Reuse from `GereksinimKarsilastirma` (patterns, not runtime coupling):**

- Ollama JSON-mode client patterns (`core/llm.py`)
- Text normalization helpers (`core/normalize.py`) as reference for ID/ref normalization
- openpyxl export awareness — but checklist export must **copy template workbook**, not rebuild sheets from scratch

**Do not** install into that app’s venv or share its Ollama models/data by default.

---

## 2. Host / environment inspection (this agent VM)

Facts from the **current Cloud Agent VM** (not assumed production server):

| Resource | Observed |
|---|---|
| OS / CPU | Linux, 4× Intel Xeon, no GPU (`nvidia-smi` / `/dev/nvidia*` absent) |
| RAM | ~16 GiB total, ~5 GiB available at inspect time |
| Disk | ~254 GiB, ~247 GiB free |
| Docker | **Not installed** in this VM (`docker` / `compose` unavailable) |
| Port probe (localhost) | `18080`, `5432`, `6333`, `11434`, `8000`, `8080`, `8501` appeared **free** via TCP connect |
| Existing containers / networks / GPU | **Cannot inventory** — no Docker daemon access here |

**Production / target server:** treat as **unknown**. All bind ports, data roots, CPU/RAM/GPU limits, and model IDs are **configurable** via `.env`. Preflight script must run **on the deploy host** before `compose up`.

If the target host has insufficient RAM/CPU/GPU or a port/project conflict: **fail loudly**. Do not stop other services to free capacity. Port/network isolation ≠ GPU isolation.

---

## 3. Product flow (v1)

```
Upload document
  → extract bibliographic / clause references
  → match against catalog + project sources (upload missing)
  → reference validation UI (before checklist)
  → evaluate one checklist (independent items; missing refs → INSUFFICIENT_EVIDENCE, not hard-block)
  → human review
  → download filled Excel copy (template features preserved)
```

### Reference validation statuses

`VERIFIED` · `METADATA_MISMATCH` · `VERSION_UNSPECIFIED` · `VERSION_MISMATCH` · `CLAUSE_NOT_FOUND` · `CLAIM_NOT_SUPPORTED` · `MISSING_SOURCE` · `AMBIGUOUS_MATCH` · `INSUFFICIENT_EVIDENCE` · `MANUAL_REVIEW`

Checks (planned): bibliographic identity, consistency, clause presence, claim support, applicability.

### Checklist answer states (engine)

Deterministic and LLM-backed methods with evidence grounding (Ollama JSON schema). States include pass/fail/partial/N/A/insufficient evidence/manual review (exact enum locked in Phase 4).

---

## 4. Target architecture

```
                    ┌─────────────────────────────────────────────┐
 Host               │  ONLY published port: GATEWAY_HOST_PORT     │
                    │  (candidate 18080 — preflight-checked)      │
                    └────────────────────┬────────────────────────┘
                                         │
┌────────────────────────────────────────▼────────────────────────┐
│ Compose project: anova-checklist-review                         │
│ Network: acr_net (bridge, internal to project)                  │
│                                                                 │
│  gateway (nginx) ──► api (FastAPI/uvicorn)                      │
│                         │                                       │
│                         ├─► postgres  (NO host publish)         │
│                         ├─► qdrant    (NO host publish)         │
│                         ├─► ollama    (NO host publish; LLM=1)  │
│                         └─► embedding (BGE-M3; NO host publish) │
│                                                                 │
│ Named volumes (project-scoped only):                            │
│   acr_pg_data, acr_qdrant_data, acr_ollama_data,                │
│   acr_embedding_cache, acr_app_uploads, acr_app_exports         │
└─────────────────────────────────────────────────────────────────┘
```

### Hard isolation rules (enforced)

- Do **not** modify existing containers, volumes, or data dirs on the host
- Separate Compose network + volumes; **no** generic `container_name`; **no** `network_mode: host`
- Do **not** publish PostgreSQL, Qdrant, Ollama, or embedding ports to the host
- Only gateway gets a configurable host port; never hard-bind without preflight
- Do not install into existing Python envs or share existing Ollama model store / Postgres data by default
- No global Docker cleanup; maintenance scoped to `-p anova-checklist-review`
- Configurable resource limits; embedding may run on **CPU**
- On conflict / insufficient resources: abort with clear errors

### Qdrant collections (planned)

| Collection | Purpose |
|---|---|
| `standards_bgem3_v1` | Standard catalog chunks (dense 1024 + sparse hybrid) |
| `project_documents_bgem3_v1` | Project-uploaded source chunks |

### Job queue

PostgreSQL-backed jobs with **leases** (no Redis). Worker(s) inside `api` process or dedicated `worker` service later; v1 concurrency for Ollama calls = **1**.

---

## 5. Data model (PostgreSQL)

Core tables (Phase 1 migrations scaffolded):

| Table | Role |
|---|---|
| `users` | Accounts |
| `projects` | Review projects |
| `memberships` | User↔project roles |
| `documents` / `document_versions` | Uploaded docs + versioned blobs/metadata |
| `standard_catalog` / `standard_versions` / `standard_aliases` | Normative catalog |
| `project_standard_sets` | Project’s selected standards set |
| `extracted_references` | Refs pulled from a document version |
| `reference_matches` / `reference_findings` | Match candidates + validation findings/status |
| `checklist_definitions` / `checklist_items` / `checklist_runs` / `checklist_answers` | Checklist engine |
| `reviews` / `review_items` | Human review sessions |
| `evidence_links` | Answer/finding ↔ source spans |
| `reviewer_decisions` | Override / accept / reject |
| `jobs` | Queue + lease columns |
| `exports` | Excel export artifacts |
| `audit_events` | Append-only audit |

---

## 6. Phased delivery

### Phase 1 — Foundation (**done**)

1. Repo inspection + this plan
2. SQLAlchemy models + Alembic migration for core tables
3. Docker Compose isolation skeleton (`gateway`, `api`, `postgres`, `qdrant`, `ollama`, `embedding`)
4. `.env.example` + `scripts/preflight_check.py`
5. Minimal FastAPI app that boots health/DB checks against the stack
6. Unit tests for reference normalization stubs + Compose config sanity

**Acceptance (Phase 1):**

- [x] `docs/implementation-plan.md` reflects real repo findings and configurable unknowns
- [ ] `docker compose -p anova-checklist-review config` validates (on a Docker host) — **blocked in agent VM (no Docker)**
- [x] Preflight fails clearly on busy gateway port / missing Docker / low resources
- [x] Alembic migration creates listed tables
- [ ] `GET /health` and `GET /ready` work when stack is up — `/health` unit-tested; `/ready` needs Postgres
- [x] No host ports for postgres/qdrant/ollama/embedding in compose
- [x] Pinned image/dep versions (no `:latest` in prod compose)

### Phase 2 — Documents + catalog + indexing (**implemented**)

Landed in `anova-checklist-review/`:

| Area | What |
|---|---|
| Upload / storage | `POST /api/v1/projects/{id}/documents` preserves original bytes under `{project}/{doc}/{version}/original__…`, SHA-256, doc_type, revision (`version_label`); new revision ≠ overwrite |
| Extraction | PDF/DOCX/XLSX/CSV/code scaffolding with locators; issues `OCR_NEEDED` / `UNREADABLE` / `UNSUPPORTED_FORMAT` recorded in `document_versions.meta.extraction` |
| Catalog APIs | Standards + versions + aliases + project standard-sets CRUD |
| Jobs | Postgres queue: `extract_document` → `index_document` / `index_standard`; `reindex_project`; lease + heartbeat; `idempotency_key` (migration `20261003_0002`) |
| Qdrant | Collections `standards_bgem3_v1` / `project_documents_bgem3_v1`, named vectors `dense`+`sparse`, payload indexes for ids/sha/chunk_index/… |
| Embedding | Separate service; default deterministic hybrid stub; optional real BGE-M3 via `EMBEDDING_LOAD_MODEL=1` + `embedding/requirements-ml.txt` |
| UI hook | Minimal `/ui` upload page (not full validation UI) |

**Job types (actual):** `extract_document`, `index_document`, `index_standard`, `reindex_project`  
(Plan earlier said `ingest_document` — renamed to clearer `extract_document`.)

**Acceptance (Phase 2):**

- [x] Upload preserves original + sha + revision separation
- [x] Extractors emit source locators + issue codes (no OCR engine yet)
- [x] Catalog/version/alias APIs
- [x] Indexer targets both Qdrant collections with hybrid vectors + payload indexes
- [x] Queue lease/heartbeat/idempotency
- [x] Unit tests for extraction/chunking/storage/jobs/qdrant payload/embedding client
- [ ] End-to-end against live Compose (Postgres+Qdrant+embedding) — **requires Docker host**
- [ ] Real BGE-M3 weights loaded — **optional; not default on CPU-slim agent/deploy**

**Known gaps (Phase 2):**

- No OCR (scanned PDFs → `OCR_NEEDED` only)
- Embedding stub used unless `EMBEDDING_LOAD_MODEL=1` and ML deps installed
- Agent/dev VM still has no Docker — full stack exercise deferred to deploy host
- No reference-validation UI (Phase 3)
- Auth remains `dev` token / `open` for tests
- DOC (legacy `.doc`) / PPT not supported

### Phase 3 — Reference extract / match / validation UI *(plan only)*

- Extraction + normalization rules (doc IDs, revisions, clauses, titles)
- Hybrid retrieval + deterministic metadata match
- Missing-source upload flow
- Validation UI **before** checklist evaluation
- Statuses listed in §3; missing refs do not block independent checklist items

### Phase 4 — Software Code Standard checklist *(plan only)*

- First checklist definition + item methods (rule / retrieval / LLM JSON-schema)
- Ollama concurrency 1; evidence grounding required in schema
- Persist answers + evidence_links

### Phase 5 — Human review + Excel export *(plan only)*

- Reviewer UI; decisions + audit
- Template-preserving Excel write (`openpyxl` load + cell fill); add **Reference Validation** sheet without destroying template features
- Download via `exports`

### Phase 6 — DataICD deterministic + SECI cross-doc *(plan only)*

- Deterministic ICD checks where possible
- Cross-document SECI consistency

### Phase 7 — Expand other checklists *(plan only)*

- Additional checklist packs driven by `checklist_definitions` data, not hard-coded UI

---

## 7. Known unknowns / configurable server parameters

| Parameter | Env key | Notes |
|---|---|---|
| Gateway host port | `GATEWAY_HOST_PORT` | Candidate `18080`; must pass preflight |
| Gateway bind address | `GATEWAY_BIND` | Default `127.0.0.1` recommended on shared hosts |
| Data root (optional bind mounts) | `ACR_DATA_ROOT` | Default: Compose named volumes only |
| Postgres creds/db | `POSTGRES_*` | Internal only |
| Resource limits | `*_MEM_LIMIT`, `*_CPU_LIMIT` | Tune per host; embedding CPU-heavy |
| Ollama model | `OLLAMA_LLM_MODEL` | e.g. `qwen2.5:7b` / `llama3.2:3b` — verify on host VRAM |
| Embedding device | `EMBEDDING_DEVICE` | `cpu` default; `cuda` only if host NVIDIA runtime confirmed |
| BGE-M3 model id/revision | `EMBEDDING_MODEL_ID`, `EMBEDDING_MODEL_REVISION` | Pin revision when known |
| Min free RAM / disk gates | `PREFLIGHT_MIN_RAM_GB`, `PREFLIGHT_MIN_DISK_GB` | Fail loud if below |
| LLM concurrency | `OLLAMA_MAX_CONCURRENCY` | v1 = `1` |
| Auth mode | `AUTH_MODE` | v1 may start as single-user/dev token |

**Do not claim** checklist accuracy rates without evaluation on real user documents.

---

## 8. UI screens (later phases)

1. Project home / memberships  
2. Document upload & versions  
3. Standard catalog & project standard set  
4. **Reference validation** (match, upload missing, statuses)  
5. Checklist run progress  
6. Item-level evidence review  
7. Export download history  
8. Admin / audit (read-only)

---

## 9. Ops notes (later)

- Backups: `pg_dump` + volume snapshots for Qdrant/uploads/exports — scoped to this Compose project
- Maintenance: `docker compose -p anova-checklist-review …` only
- Audit: every export, decision override, and source replace → `audit_events`

---

## 10. Deliverables checklist

| Deliverable | Location |
|---|---|
| This plan | `docs/implementation-plan.md` |
| App tree | `anova-checklist-review/` |
| Compose + gateway | `anova-checklist-review/docker-compose.yml`, `deploy/nginx.conf` |
| Env sample | `anova-checklist-review/.env.example` |
| Preflight | `anova-checklist-review/scripts/preflight_check.py` |
| API + migrations | `anova-checklist-review/backend/` |
| Embedding service skeleton | `anova-checklist-review/embedding/` |
| Frontend | `anova-checklist-review/frontend/` placeholder; Phase 2 uses API + `/ui` hook |
| Tests | `anova-checklist-review/backend/tests/`, embedding stub tests, compose sanity |

### Phase 2 local exercise (Docker host)

```bash
cd anova-checklist-review
cp .env.example .env
python3 scripts/preflight_check.py
docker compose -p anova-checklist-review up -d --build
TOKEN=dev-change-me
# create project
curl -sS -H "X-API-Token: $TOKEN" -H 'Content-Type: application/json' \
  -d '{"slug":"demo","name":"Demo"}' http://127.0.0.1:18080/api/v1/projects
# upload (replace PROJECT_ID)
curl -sS -H "X-API-Token: $TOKEN" \
  -F file=@./README.md -F doc_type=code -F version_label=1 \
  http://127.0.0.1:18080/api/v1/projects/PROJECT_ID/documents
# poll job / document-version until meta.indexing.status=ok
# or open http://127.0.0.1:18080/ui
```

---

## 11. Pin policy

- Compose images and Python deps use **explicit versions** verified installable from PyPI/Docker Hub at scaffold time (see `.env.example` / `requirements.txt`).
- Never ship `:latest` for production services.
- Model weights (Ollama + BGE-M3) are pulled into **project volumes**, not shared host stores by default.
