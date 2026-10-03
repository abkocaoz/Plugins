# Onboarding a real checklist template

Production `.xlsx` / `.xlsm` templates are **not** in this repository. The registry does **not** invent 21 full checklists. It provides:

1. Implemented scaffolds (Software Code Standard, DataICD, SECI) with synthetic fixtures for tests
2. Thin representative scaffolds (Requirements Traceability, Configuration Management)
3. Empty `awaiting_template` slots you can activate when a real workbook arrives

Inspect the registry:

```bash
curl -sS -H "X-API-Token: $TOKEN" "$BASE/api/v1/checklists/registry"
```

## Steps to add a real template

1. **Place the workbook** under `anova-checklist-review/templates/excel/` (or another path mounted into the API).
2. **Author a catalog JSON** in `backend/app/catalogs/<definition_key>_v1.json` with:
   - `key` / `title` / `version_label`
   - `excel_template_path` (absolute or relative to `catalogs/`)
   - `cell_mapping.columns` for Answer, Chapter, Comment, References, Reviewed Item, Status (and `is_applicable` when needed)
   - Per-item `excel_cells`, `method`, `method_config`, `subchecks`, `acceptance_criteria`
   - `template_gap.claimed_template_file_count` reflecting reality (only count files you actually ship)
3. **Register** the definition in `backend/app/catalogs/checklist_registry.json`:
   - `status`: `scaffold_implemented` or your org’s label
   - `catalog_file`, `seedable: true`
   - optional `synthetic_fixture` for tests
4. **Validate** (dry-run API or unit helper):

```bash
curl -sS -X POST -H "X-API-Token: $TOKEN" -H 'Content-Type: application/json' \
  -d @onboard-payload.json \
  "$BASE/api/v1/checklists/registry/validate-onboarding"
```

5. **Seed** and run:

```bash
curl -sS -X POST -H "X-API-Token: $TOKEN" \
  "$BASE/api/v1/checklists/seed/<definition-key-with-hyphens>"
```

6. Export uses the same Phase 5 path: load template → fill a **copy** → never mutate the original.

## Rules to preserve

- Do not invent columns like Author’s Answer or Resolved SVN Revision unless the real template has them
- Do not set Status=`Closed` just because AI answered
- Keep applicability (`Is Applicable`) separate from conformity (`Answer`) — especially DataICD-style sheets
- Blank Yes/No/NA answers for `INSUFFICIENT_EVIDENCE` / `MANUAL_REVIEW` / `ERROR`; put explanation in Comment
- Prefix formula-injection-prone external text (`=`, `+`, `-`, `@`)

## Empty slots

`awaiting_template` entries (e.g. `design_review`, `test_evidence`) are **placeholders**. Seeding them returns HTTP 409 until a catalog file exists. That is intentional.
