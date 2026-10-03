# Excel templates

Place **production** checklist Excel templates here (or configure paths in
`checklist_definitions.excel_template_path`).

## Gap (honest)

**No production Software Code Standard `.xlsx` / `.xlsm` was found in this repository.**
Do **not** assume that 21 (or any other count of) real template workbooks exist as files.

Phase 5 ships a **minimal synthetic fixture** used only for cell-mapping and
preservation tests:

`backend/app/catalogs/fixtures/software_code_standard_synthetic_v1.xlsx`

Regenerate with:

```bash
cd backend && python scripts/generate_synthetic_scs_template.py
```

Catalog + per-item cell maps live in:

`backend/app/catalogs/software_code_standard_v1.json`

Mapped columns (explicit; nothing invented beyond these):

| Role | Column |
|---|---|
| Answer | C |
| Chapter | D |
| Comment | E |
| References | F |
| Reviewed Item | G |
| Status | H |

**Not invented:** Author’s Answer, Resolved SVN Revision.

**Status policy:** never set `Status=Closed` solely because the AI answered; only a
human-supplied status is written on export.

**Yes/No/NA answers:** for `INSUFFICIENT_EVIDENCE`, `MANUAL_REVIEW`, and `ERROR`,
leave the Answer cell blank and put the explanation in Comment.

**DataICD (Phase 6):** synthetic fixture
`backend/app/catalogs/fixtures/data_icd_synthetic_v1.xlsx` — column **Is Applicable**
is separate from **Answer** (conformity); never write conformity into Is Applicable.

**SECI (Phase 6):** synthetic fixture
`backend/app/catalogs/fixtures/seci_synthetic_v1.xlsx` for cross-document mapping tests.

When a real template is supplied:

1. Place it in this folder (or another configured path)
2. Set `checklist_definitions.excel_template_path` / catalog `excel_template_path`
3. Align `cell_mapping` / per-item `excel_cells` to that workbook
4. Export loads that workbook, writes into a **copy**, and preserves template features

Export must **never mutate** the original template file. It preserves:

- sheets, styles, merged cells
- formulas and defined names
- data validation / dropdowns
- print area and question order
- images when present in the source workbook

A **Reference Validation** sheet is added/updated with short findings
(ref, stated version, selected source, result, location, explanation) — without
republishing long standard text.

Formula injection: external text beginning with `=`, `+`, `-`, or `@` is prefixed
before write.
