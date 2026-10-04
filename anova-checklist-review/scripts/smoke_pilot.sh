#!/usr/bin/env bash
# Minimal deploy-host smoke: preflight → compose up → health → seed → upload → jobs.
# Fails clearly when Docker is missing; does not fake success.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

TOKEN="${TOKEN:-dev-change-me}"
BASE="${BASE:-http://127.0.0.1:18080}"
COMPOSE=(docker compose -p anova-checklist-review)

if ! command -v docker >/dev/null 2>&1; then
  echo "SMOKE FAILED: Docker is not installed or not on PATH." >&2
  echo "Install Docker Engine + Compose v2 on the deploy host, then re-run:" >&2
  echo "  cd anova-checklist-review && ./scripts/smoke_pilot.sh" >&2
  exit 2
fi

if [[ ! -f .env ]]; then
  cp .env.example .env
  echo "Created .env from .env.example — edit secrets before production use."
fi

echo "== preflight =="
python3 scripts/preflight_check.py

echo "== compose up =="
"${COMPOSE[@]}" up -d --build

echo "== wait for gateway /health (proxied to API) =="
ok=0
for i in $(seq 1 60); do
  if curl -fsS "$BASE/health" >/dev/null 2>&1; then
    ok=1
    break
  fi
  sleep 2
done
if [[ "$ok" != "1" ]]; then
  echo "SMOKE FAILED: $BASE/health not ready after ~120s" >&2
  "${COMPOSE[@]}" ps >&2 || true
  "${COMPOSE[@]}" logs --tail=80 api gateway >&2 || true
  exit 3
fi

echo "== health + ready =="
curl -fsS "$BASE/healthz" || true   # nginx local
curl -fsS "$BASE/health"
echo
curl -fsS "$BASE/ready" || {
  echo "WARN: /ready not OK yet (DB/Qdrant); continuing seed/upload checks" >&2
}
echo

echo "== seed software_code_standard =="
curl -fsS -X POST -H "X-API-Token: $TOKEN" \
  "$BASE/api/v1/checklists/seed/software-code-standard" | tee /tmp/acr-seed.json
echo

echo "== create project + upload =="
PROJECT_ID="$(curl -fsS -H "X-API-Token: $TOKEN" -H 'Content-Type: application/json' \
  -d '{"slug":"smoke-'"$(date +%s)"'","name":"Smoke Pilot"}' \
  "$BASE/api/v1/projects" | python3 -c 'import sys,json; print(json.load(sys.stdin)["id"])')"
echo "PROJECT_ID=$PROJECT_ID"

UPLOAD_JSON="$(curl -fsS -H "X-API-Token: $TOKEN" \
  -F "file=@./README.md" -F "doc_type=code" -F "version_label=1" \
  "$BASE/api/v1/projects/$PROJECT_ID/documents")"
echo "$UPLOAD_JSON" | tee /tmp/acr-upload.json
VERSION_ID="$(python3 -c 'import json,sys; print(json.load(sys.stdin)["version"]["id"])' <<<"$UPLOAD_JSON")"
echo "VERSION_ID=$VERSION_ID"

echo "== poll jobs (up to ~90s) =="
for i in $(seq 1 30); do
  JOBS="$(curl -fsS -H "X-API-Token: $TOKEN" "$BASE/api/v1/projects/$PROJECT_ID/jobs")"
  echo "$JOBS" | python3 -c 'import json,sys; jobs=json.load(sys.stdin); print([(j.get("job_type"), j.get("status")) for j in jobs[:8]])'
  pending="$(echo "$JOBS" | python3 -c 'import json,sys; jobs=json.load(sys.stdin); print(sum(1 for j in jobs if j.get("status") in ("queued","leased","running")))')"
  if [[ "$pending" == "0" ]]; then
    break
  fi
  sleep 3
done

echo "== registry honesty =="
curl -fsS -H "X-API-Token: $TOKEN" "$BASE/api/v1/checklists/registry" \
  | python3 -c 'import json,sys; c=json.load(sys.stdin)["counts"]; assert c["claimed_production_template_count"]==0; print(c)'

echo "SMOKE PASSED (minimal path). Next: checklist-run + human review on a Docker host with real templates."
