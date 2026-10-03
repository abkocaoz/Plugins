# Anova Checklist Review — Implementation Plan

**Project:** Reviewer / `anova-checklist-review`  
**Stack (v1):** FastAPI + PostgreSQL + Qdrant + BGE-M3 (separate embedding service) + Ollama + React/TypeScript  
**Compose project name:** `anova-checklist-review`  
**Status:** Phase 5 (human review + Excel export) implemented on branch; Phase 6+ not started

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

### Phase 3 — Reference extract / match / validation (**implemented**)

| Area | What |
|---|---|
| Extraction | References/Applicable Documents sections + body citations; table/footnote/header/footer kinds; OCR/unreadable gaps recorded |
| Structured records | `extracted_references` fields (id/title/rev/supplement/publisher/date/clause/section/normalization_version); uncertain → NULL (never invented) |
| Normalization | Versioned `refnorm-v3.1`; revision ≠ supplement preserved; alias table used in matching |
| Auto-match priority | id+revision → id+supplement → id+publisher+title → semantic **candidates only**; never auto-pick by embedding alone |
| Unspecified revision | Project approved set as candidates; `VERSION_UNSPECIFIED`; user must choose — never silent latest |
| Missing source | `GET …/missing-references`; upload with `expected_doc_id` verifies **content** not filename; index then re-resolve affected refs only |
| Validation | bibliographic / consistency / clause / applicability → distinct statuses + findings (location, selected source/version, clause/quote, explanation, non-mutating suggested_fix) |
| Review | `GET …/reference-review` + `/ui/references` before checklist; `blocks_independent_checklist=false`; pinned `standard_version_ids` on review.meta |
| Jobs | `reference_resolution` (after indexing) → `reference_validation`; select-match requeues partial validation |

**Acceptance (Phase 3):**

- [x] Reference extraction with locators + gap codes
- [x] Structured fields without inventing uncertain data
- [x] Versioned normalization + alias-aware match
- [x] Match priority + no embedding-only auto-select
- [x] Unspecified revision asks user
- [x] Missing-source list + content identity verify
- [x] Validation findings with suggested_fix.auto_apply=false
- [x] Reference review API/UI hook before checklist
- [x] Job stages wired after index
- [x] Unit tests for normalize/match/extract/validate/identity
- [ ] Live Compose e2e — still needs Docker host

### Phase 4 — Software Code Standard checklist (**implemented**)

| Area | What |
|---|---|
| Catalog | Versioned scaffold `backend/app/catalogs/software_code_standard_v1.json` → `checklist_definitions` / `checklist_items` (seed API). **No real Excel template file in repo** (`template_gap.claimed_template_file_count=0`); cell-mapping config included for Phase 5 export |
| Item fields | question, file/sheet/number, Answer/Chapter/Comment cells, applicability, required docs, clauses, reference deps, subchecks, acceptance criteria, method + config |
| Methods | `deterministic_rule` (Python), `document_content` (Ollama JSON Schema + Pydantic), `cross_document`, `traceability` (full scan), `external_evidence`, `manual_review` |
| LLM guards | Cite only provided evidence IDs; server verifies IDs/project/revision/quote; YES needs subchecks; NA needs inapplicability rationale; confidence ≠ approval; fake IDs → ERROR |
| States | `YES` / `NO` / `NA` / `INSUFFICIENT_EVIDENCE` / `MANUAL_REVIEW` / `ERROR` — missing search ≠ NO; missing evidence ≠ NA |
| Full scan | Items with `requires_full_scan` scan all extraction units (not a few RAG hits) |
| Missing refs | Independent items run; dependent → `INSUFFICIENT_EVIDENCE` with critical ref errors surfaced |
| Pinning | `checklist_runs.meta.pinned_standard_version_ids` (+ document version) |
| Jobs / storage | `checklist_review`; `checklist_answers` + `ai_proposal` separate from `human_decision`; `evidence_links` |
| UI | `/ui/checklist` + `GET /checklist-runs/{id}/view` |

**Acceptance (Phase 4):**

- [x] Scaffold catalog + documented template gap (no invented template files)
- [x] Methods + answer semantics + evidence ID verification
- [x] Full-scan deterministic/traceability paths
- [x] Dependent vs independent reference handling
- [x] Job + APIs + minimal results UI
- [x] Unit tests (YES/NO/NA/insufficient/fake evidence)
- [ ] Live Ollama/Compose e2e — needs Docker host + Ollama model

### Phase 5 — Human review + Excel export (**implemented**)

| Area | What |
|---|---|
| Human review API | `POST /checklist-answers/{id}/decision` → `reviewer_decisions` (+ `review` / `review_items`); `ai_proposal` kept; `human_decision` / effective `state` updated; change rationale + audit |
| Evidence + refs | Existing evidence endpoint; view includes evidence + related reference findings (compact); decisions list |
| UI | `/ui/checklist` — accept/override/reject/defer, rationale, export draft / reviewer-approved |
| Excel export | Job stage `export`; fills a **copy** of template; never mutates original; `GET /exports/{id}/download` |
| Cell mapping | Explicit Answer/Chapter/Comment/References/Reviewed Item/Status; **no** Author’s Answer / Resolved SVN Revision; Status never auto-Closed from AI |
| Blank answers | Yes/No/NA template: blank Answer for `INSUFFICIENT_EVIDENCE` / `MANUAL_REVIEW` / `ERROR`; explanation in Comment |
| Reference sheet | Extra sheet **Reference Validation** (ref, stated version, selected source, result, location, explanation) — no long standard text |
| Preservation | Merged cells, data validation dropdowns, formulas, print area, question order; formula-injection prefix on `=+/ -@` |
| Template gap | Production `.xlsx` still absent; synthetic fixture `backend/app/catalogs/fixtures/software_code_standard_synthetic_v1.xlsx` for tests only (`claimed_template_file_count=0`) |
| DataICD note | Future: keep applicability vs conformity separate (documented in catalog `template_gap.dataicd_note`) |

**Acceptance (Phase 5):**

- [x] Human decisions stored separately from `ai_proposal`
- [x] Draft + reviewer-approved export modes via `export` job
- [x] Explicit cell mapping; blank-on-insufficient; injection guard; preservation basics
- [x] Synthetic fixture + honest template-gap docs (no claim of 21 real templates)
- [x] Unit tests + plan/README update
- [ ] Live Compose e2e download through gateway — needs Docker host

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
