# Setup (v1)

Deploy host with Docker Engine + Compose v2.

## 1. Clone and configure

```bash
cd anova-checklist-review
cp .env.example .env
# Edit secrets: POSTGRES_PASSWORD, DEV_API_TOKEN, GATEWAY_HOST_PORT if 18080 is busy
```

## 2. Preflight (required)

```bash
python3 scripts/preflight_check.py
```

Fails clearly on: busy gateway port, missing Docker, low RAM/disk, Compose isolation violations.

## 3. Start stack

```bash
docker compose -p anova-checklist-review up -d --build
```

Isolation rules (must hold):

- Project name `anova-checklist-review`
- Dedicated network + named volumes; **no** `container_name`; **no** `network_mode: host`
- Only **gateway** publishes a host port (`GATEWAY_BIND`:`GATEWAY_HOST_PORT`)
- Postgres, Qdrant, Ollama, embedding stay internal

## 4. Smoke

```bash
curl -sS http://127.0.0.1:18080/health
# API token from .env
curl -sS -H "X-API-Token: $TOKEN" http://127.0.0.1:18080/api/v1/checklists/registry
```

## 5. Seed checklist catalogs

```bash
curl -sS -X POST -H "X-API-Token: $TOKEN" \
  http://127.0.0.1:18080/api/v1/checklists/seed-all
```

See also: [model-prep.md](model-prep.md), [backup-restore.md](backup-restore.md), [checklist-onboarding.md](checklist-onboarding.md), [known-limitations.md](known-limitations.md).

Maintenance must stay scoped:

```bash
docker compose -p anova-checklist-review ps
docker compose -p anova-checklist-review logs -f api
docker compose -p anova-checklist-review down
```
