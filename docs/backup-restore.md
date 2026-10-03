# Backup / restore (Postgres + file store + Qdrant)

Scope all commands to Compose project `anova-checklist-review`. Do not touch other stacks’ volumes.

## What to back up

| Store | Compose volume (default) | Contents |
|---|---|---|
| Postgres | `anova-checklist-review_acr_pg_data` | Projects, jobs, answers, reviews, exports metadata |
| Uploads | `anova-checklist-review_acr_app_uploads` | Original document bytes |
| Exports | `anova-checklist-review_acr_app_exports` | Filled Excel export files |
| Qdrant | `anova-checklist-review_acr_qdrant_data` | Vector indexes (`standards_bgem3_v1`, `project_documents_bgem3_v1`) |

Ollama model layers live in `anova-checklist-review_acr_ollama_data` (optional to back up; can re-pull).

## Backup (example)

```bash
PROJECT=anova-checklist-review
STAMP=$(date -u +%Y%m%dT%H%M%SZ)
OUT=./backups/$STAMP
mkdir -p "$OUT"

# Postgres logical dump
docker compose -p "$PROJECT" exec -T postgres \
  pg_dump -U "${POSTGRES_USER:-acr}" -d "${POSTGRES_DB:-acr}" -Fc \
  > "$OUT/acr.dump"

# File volumes (uploads + exports) via temporary alpine
docker run --rm \
  -v "${PROJECT}_acr_app_uploads:/uploads:ro" \
  -v "${PROJECT}_acr_app_exports:/exports:ro" \
  -v "$PWD/$OUT:/backup" alpine:3.20 \
  sh -c 'tar czf /backup/files.tgz -C / uploads exports'

# Qdrant storage
docker run --rm \
  -v "${PROJECT}_acr_qdrant_data:/qdrant:ro" \
  -v "$PWD/$OUT:/backup" alpine:3.20 \
  sh -c 'tar czf /backup/qdrant.tgz -C / qdrant'
```

Store `$OUT` off-host. Encrypt at rest if required by your org.

## Restore (outline)

1. `docker compose -p anova-checklist-review down`
2. Restore volume tarballs into the named volumes (stop services first).
3. Restore Postgres: `pg_restore` into a fresh/clean DB volume.
4. `docker compose -p anova-checklist-review up -d`
5. Spot-check: `/health`, sample project, Qdrant collection counts, one export download.

If vectors and files diverge, prefer **reindex** (`reindex_project` job) after files + Postgres are consistent.

## Notes

- Prefer named volumes (default). If using `ACR_DATA_ROOT` bind mounts, back up those host paths instead.
- Never run global `docker volume prune` on a shared host.
- Export rows in Postgres point at paths under `/data/exports`; restore files to matching paths.
