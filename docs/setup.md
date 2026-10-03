# Setup (v1)

Deploy host with **Docker Engine + Compose v2**. Agent/CI VMs without Docker cannot complete the compose smoke — that is expected, not a fake pass.

## Prerequisites

| Requirement | Notes |
|---|---|
| Docker Engine + `docker compose` plugin | Preflight fails if missing |
| Free RAM ≥ `PREFLIGHT_MIN_RAM_GB` (default **8**) | Preflight refuses to proceed |
| Free disk ≥ `PREFLIGHT_MIN_DISK_GB` (default **20**) | Preflight refuses to proceed |
| Free gateway port | Default `127.0.0.1:18080` |

## 1. Clone and configure

```bash
cd anova-checklist-review
cp .env.example .env
# Required edits before real deploy:
#   POSTGRES_PASSWORD, DEV_API_TOKEN
#   GATEWAY_HOST_PORT if 18080 is busy
# Optional: OLLAMA_LLM_MODEL, EMBEDDING_LOAD_MODEL=1 (see model-prep.md)
```

## 2. Preflight (required)

```bash
python3 scripts/preflight_check.py
```

Fails clearly on: missing Docker, busy gateway port, low RAM/disk, Compose isolation violations.

Unit-test / no-Docker hosts only:

```bash
python3 scripts/preflight_check.py --skip-docker
```

## 3. Start stack **or** one-shot smoke

```bash
docker compose -p anova-checklist-review up -d --build
```

Or the scripted minimal path (preflight → up → `/health` → seed → upload → poll jobs):

```bash
./scripts/smoke_pilot.sh
# TOKEN / BASE env vars optional; defaults match .env.example
```

Isolation rules (must hold):

- Project name `anova-checklist-review`
- Dedicated network + named volumes; **no** `container_name`; **no** `network_mode: host`
- Only **gateway** publishes a host port (`GATEWAY_BIND`:`GATEWAY_HOST_PORT`)
- Postgres, Qdrant, Ollama, embedding stay internal

## 4. Manual smoke checks

```bash
TOKEN=dev-change-me   # must match DEV_API_TOKEN in .env
BASE=http://127.0.0.1:18080

curl -sS "$BASE/health"
curl -sS -H "X-API-Token: $TOKEN" "$BASE/api/v1/checklists/registry"
# ready (API via gateway) — path depends on nginx; also try:
curl -sS "$BASE/ready" || true
```

## 5. Seed checklist catalogs

```bash
curl -sS -X POST -H "X-API-Token: $TOKEN" \
  "$BASE/api/v1/checklists/seed-all"
```

Production Excel templates are **not** shipped. Registry stays at
`claimed_production_template_count=0` until you onboard real workbooks
([checklist-onboarding.md](checklist-onboarding.md)).

See also: [model-prep.md](model-prep.md), [backup-restore.md](backup-restore.md), [known-limitations.md](known-limitations.md).

Maintenance must stay scoped:

```bash
docker compose -p anova-checklist-review ps
docker compose -p anova-checklist-review logs -f api
docker compose -p anova-checklist-review down
```
