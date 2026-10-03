# Anova Checklist Review

Internal document-review + Excel checklist application.

See [`../docs/implementation-plan.md`](../docs/implementation-plan.md) for architecture, phases, and isolation rules.

## Phase 1 (current)

- FastAPI skeleton (`backend/`)
- PostgreSQL schema via Alembic
- Isolated Docker Compose project `anova-checklist-review`
- Preflight script (port / resources / isolation)
- BGE-M3 embedding service skeleton (separate from Ollama)

## Quick start (deploy host with Docker)

```bash
cd anova-checklist-review
cp .env.example .env
# edit secrets + GATEWAY_HOST_PORT after checking availability
python3 scripts/preflight_check.py
docker compose -p anova-checklist-review up -d --build
curl -sS "http://${GATEWAY_BIND:-127.0.0.1}:${GATEWAY_HOST_PORT:-18080}/health"
```

Maintenance must stay scoped to this project:

```bash
docker compose -p anova-checklist-review ps
docker compose -p anova-checklist-review logs -f api
docker compose -p anova-checklist-review down   # does not touch other stacks
```

## Local API tests (no Docker)

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pytest -q
```

`GET /ready` requires a reachable Postgres (`DATABASE_URL`).

## Frontend

No existing React app was found in the repository. UI will be added as React + TypeScript under `frontend/` in later phases. Phase 1 ships a placeholder only.
