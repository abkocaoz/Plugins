# Anova Checklist Review — Implementation Plan

**Project:** Reviewer / `anova-checklist-review`  
**Stack (v1):** FastAPI + PostgreSQL + Qdrant + BGE-M3 (separate embedding service) + Ollama + React/TypeScript  
**Compose project name:** `anova-checklist-review`  
**Status:** Phase 1 foundation in progress

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

### Phase 1 — Foundation (**implement now**)

1. Repo inspection + this plan
2. SQLAlchemy models + Alembic migration for core tables
3. Docker Compose isolation skeleton (`gateway`, `api`, `postgres`, `qdrant`, `ollama`, `embedding`)
4. `.env.example` + `scripts/preflight_check.py`
5. Minimal FastAPI app that boots health/DB checks against the stack
6. Unit tests for reference normalization stubs + Compose config sanity

**Acceptance (Phase 1):**

- [ ] `docs/implementation-plan.md` reflects real repo findings and configurable unknowns
- [ ] `docker compose -p anova-checklist-review config` validates (on a Docker host)
- [ ] Preflight fails clearly on busy gateway port / missing Docker / low resources
- [ ] Alembic migration creates listed tables
- [ ] `GET /health` and `GET /ready` work when stack is up
- [ ] No host ports for postgres/qdrant/ollama/embedding in compose
- [ ] Pinned image/dep versions (no `:latest` in prod compose)

### Phase 2 — Documents + catalog + indexing *(plan only)*

- Upload PDF/DOCX/XLSX/CSV/code; extract text/structure
- Standard catalog CRUD + aliases
- Chunking + BGE-M3 dense(1024)+sparse upsert into Qdrant collections
- Job types: `ingest_document`, `index_standard`, `reindex_project`

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
| Frontend (Phase 1 placeholder) | `anova-checklist-review/frontend/` README only until Phase 3+ |
| Tests | `anova-checklist-review/backend/tests/`, compose sanity tests |

---

## 11. Pin policy

- Compose images and Python deps use **explicit versions** verified installable from PyPI/Docker Hub at scaffold time (see `.env.example` / `requirements.txt`).
- Never ship `:latest` for production services.
- Model weights (Ollama + BGE-M3) are pulled into **project volumes**, not shared host stores by default.
