# Excel templates

Place checklist Excel templates here (or configure paths in `checklist_definitions.excel_template_path`).

## Gap (Phase 4)

**No real Software Code Standard `.xlsx` / `.xlsm` file is present in this repository.**
Phase 4 therefore seeds a versioned JSON catalog + cell-mapping scaffold at:

`backend/app/catalogs/software_code_standard_v1.json`

That scaffold is the checklist catalog (`checklist_definitions` / `checklist_items`). It does **not** invent that multiple template workbooks exist as files (`claimed_template_file_count: 0`).

When a real template is supplied:

1. Place it in this folder
2. Set `checklist_definitions.excel_template_path`
3. Align `cell_mapping` / per-item `excel_cells` to the workbook
4. Phase 5 export will load that workbook and fill Answer/Chapter/Comment cells while preserving template features

Export must **load the template workbook** and write cell values while preserving:

- sheets, styles, merged cells
- formulas and defined names
- data validation / conditional formatting
- any VBA-enabled features supported by the chosen writer (prefer `.xlsx` openpyxl-safe templates)

A **Reference Validation** sheet may be added/updated without destroying other template features.
