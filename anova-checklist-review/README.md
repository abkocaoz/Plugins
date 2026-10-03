# Anova Checklist Review

Internal document-review + Excel checklist application.

See [`../docs/implementation-plan.md`](../docs/implementation-plan.md) for architecture, phases, and isolation rules.

## Current status: Phase 6

Upload → extract → index → references → checklist evaluation (Software Code Standard, **DataICD**, **SECI**) → human review + Excel export.

Catalogs are versioned JSON scaffolds. Production Excel templates are **not** in the repo; synthetic `.xlsx` fixtures support mapping/preservation tests (see `templates/excel/README.md`). Do not assume 21 real templates exist. Phase 7 (remaining checklists) is not started.

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

# 3) Poll jobs (extract → index → reference_resolution → reference_validation)
curl -sS -H "X-API-Token: $TOKEN" "$BASE/api/v1/projects/$PROJECT_ID/jobs"

# 4) After jobs succeed, open reference review (VERSION_ID from upload response)
# curl -sS -H "X-API-Token: $TOKEN" "$BASE/api/v1/document-versions/$VERSION_ID/reference-review"
# curl -sS -H "X-API-Token: $TOKEN" "$BASE/api/v1/document-versions/$VERSION_ID/missing-references"
# open $BASE/ui and $BASE/ui/references
```

### Checklist + human review + export (Phases 4–6)

```bash
# Seed catalogs (safe to repeat)
curl -sS -X POST -H "X-API-Token: $TOKEN" \
  "$BASE/api/v1/checklists/seed/software-code-standard"
curl -sS -X POST -H "X-API-Token: $TOKEN" \
  "$BASE/api/v1/checklists/seed/data-icd"
curl -sS -X POST -H "X-API-Token: $TOKEN" \
  "$BASE/api/v1/checklists/seed/seci"

# Start evaluation job (after document extracted/indexed)
curl -sS -X POST -H "X-API-Token: $TOKEN" -H 'Content-Type: application/json' \
  -d "{\"document_version_id\":\"$VERSION_ID\",\"definition_key\":\"software_code_standard\"}" \
  "$BASE/api/v1/projects/$PROJECT_ID/checklist-runs"

# DataICD (deterministic; Is Applicable ≠ Answer/conformity)
curl -sS -X POST -H "X-API-Token: $TOKEN" -H 'Content-Type: application/json' \
  -d "{\"document_version_id\":\"$ICD_VERSION_ID\",\"definition_key\":\"data_icd\"}" \
  "$BASE/api/v1/projects/$PROJECT_ID/checklist-runs"

# SECI cross-document (pin peer ICD/design versions on the run)
curl -sS -X POST -H "X-API-Token: $TOKEN" -H 'Content-Type: application/json' \
  -d "{\"document_version_id\":\"$SECI_VERSION_ID\",\"definition_key\":\"seci\",\"pinned_document_version_ids\":[\"$ICD_VERSION_ID\"]}" \
  "$BASE/api/v1/projects/$PROJECT_ID/checklist-runs"

# When job result includes checklist_run_id:
curl -sS -H "X-API-Token: $TOKEN" "$BASE/api/v1/checklist-runs/$RUN_ID/view"
# or open $BASE/ui/checklist

# Record human decision (ai_proposal stays; reviewer_decisions row created)
curl -sS -X POST -H "X-API-Token: $TOKEN" -H 'Content-Type: application/json' \
  -d '{"decision":"override","override_state":"YES","change_rationale":"Confirmed in source","status_value":"In Review","reviewed_item":"Yes"}' \
  "$BASE/api/v1/checklist-answers/$ANSWER_ID/decision"

# Export filled copy of template (draft | reviewer_approved) — job type export
curl -sS -X POST -H "X-API-Token: $TOKEN" -H 'Content-Type: application/json' \
  -d '{"mode":"draft"}' \
  "$BASE/api/v1/checklist-runs/$RUN_ID/export"

# After export job succeeds:
curl -sS -H "X-API-Token: $TOKEN" "$BASE/api/v1/checklist-runs/$RUN_ID/exports"
curl -sS -H "X-API-Token: $TOKEN" -o filled.xlsx \
  "$BASE/api/v1/exports/$EXPORT_ID/download"
```

### Missing source upload (content identity)

```bash
curl -sS -H "X-API-Token: $TOKEN" \
  -F "file=@./DO178C.pdf" -F "doc_type=standard" -F "version_label=B" \
  -F "standard_version_id=$STD_VER_ID" \
  -F "expected_doc_id=DO-178C" \
  -F "fills_missing_reference_id=$EXTRACTED_REF_ID" \
  "$BASE/api/v1/projects/$PROJECT_ID/documents"
```

Filename is ignored for identity; content must confirm `expected_doc_id`.

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

No full React SPA yet. REST APIs + `/ui`, `/ui/references`, `/ui/checklist` hooks for upload, references, human review, and export.
