# Anova Checklist Review

Internal document-review + Excel checklist application.

See [`../docs/implementation-plan.md`](../docs/implementation-plan.md) for architecture, phases, and isolation rules.

## Current status: Phase 2

Upload → extract → index pipeline with Postgres job leases, standard catalog APIs, and Qdrant hybrid indexing (dense 1024 + sparse) via a **separate** BGE-M3 embedding service.

## Quick start (deploy host with Docker)

```bash
cd anova-checklist-review
cp .env.example .env
# edit secrets + GATEWAY_HOST_PORT after checking availability
python3 scripts/preflight_check.py
docker compose -p anova-checklist-review up -d --build
```

Exercise upload → extract → index:

```bash
TOKEN=dev-change-me
BASE=http://127.0.0.1:18080   # or your GATEWAY_BIND:GATEWAY_HOST_PORT

# 1) Project
PROJECT_ID=$(curl -sS -H "X-API-Token: $TOKEN" -H 'Content-Type: application/json' \
  -d '{"slug":"demo","name":"Demo Project"}' "$BASE/api/v1/projects" | python3 -c 'import sys,json; print(json.load(sys.stdin)["id"])')

# 2) Upload (creates extract_document job; worker chains index_*)
curl -sS -H "X-API-Token: $TOKEN" \
  -F "file=@./README.md" -F "doc_type=code" -F "version_label=1" \
  "$BASE/api/v1/projects/$PROJECT_ID/documents"

# 3) Poll jobs
curl -sS -H "X-API-Token: $TOKEN" "$BASE/api/v1/projects/$PROJECT_ID/jobs"

# 4) Or use minimal UI hook
# open $BASE/ui
```

Standard catalog example:

```bash
curl -sS -H "X-API-Token: $TOKEN" -H 'Content-Type: application/json' \
  -d '{"canonical_key":"DO-178C","title":"Software Considerations…"}' \
  "$BASE/api/v1/standards"
```

Maintenance must stay scoped to this project:

```bash
docker compose -p anova-checklist-review ps
docker compose -p anova-checklist-review logs -f api
docker compose -p anova-checklist-review down
```

### Embedding modes

| `EMBEDDING_LOAD_MODEL` | Behavior |
|---|---|
| `0` (default) | Deterministic dense+sparse stub — pipeline wiring without multi-GB download |
| `1` | Real `BAAI/bge-m3` via FlagEmbedding (`embedding/requirements-ml.txt`); needs RAM/CPU or CUDA |

## Local unit tests (no Docker)

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pytest -q
# embedding stub:
cd ../embedding && PYTHONPATH=. pytest -q test_embed_stub.py
```

`GET /ready` and live indexing require Postgres + Qdrant + embedding from Compose.

## Frontend

No full React SPA yet. Phase 2 ships REST APIs + `/ui` upload hook. React/TS planned for Phase 3+ validation UI.
