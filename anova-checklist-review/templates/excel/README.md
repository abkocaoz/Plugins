# Excel templates

Place checklist Excel templates here (or configure paths in `checklist_definitions.excel_template_path`).

Export must **load the template workbook** and write cell values while preserving:

- sheets, styles, merged cells
- formulas and defined names
- data validation / conditional formatting
- any VBA-enabled features supported by the chosen writer (prefer `.xlsx` openpyxl-safe templates)

A **Reference Validation** sheet may be added/updated without destroying other template features.
