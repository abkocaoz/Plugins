# Known limitations & pilot notes (v1)

## Honesty

- **No accuracy claims** without evaluation on real user documents and real checklist templates.
- **No claim that 21 Excel templates exist** in this repo. Production workbooks must be supplied; see [checklist-onboarding.md](checklist-onboarding.md).
- Synthetic `.xlsx` fixtures exist only for mapping/preservation tests.

## Production-ready vs scaffold-only

| Area | Status |
|---|---|
| Compose isolation, preflight, `.env.example` | Production-oriented scaffolding |
| Upload / extract / index / jobs | Implemented; needs live stack for e2e |
| Reference extraction / validation | Implemented; catalog quality depends on seeded standards |
| Software Code Standard / DataICD / SECI engines | Scaffold + rules; limited item sets |
| Human review + Excel export | Implemented against synthetic or supplied templates |
| Requirements Traceability / CM catalogs | Thin representative scaffolds |
| Other registry slots | `awaiting_template` only |
| React SPA | Not shipped; `/ui` hooks only |
| Auth | Dev token / open modes — not full IdP SSO |
| Embedding | Default stub (`EMBEDDING_LOAD_MODEL=0`); real BGE-M3 optional |
| Ollama | Requires model pull on deploy host |

## Pilot recommendations

1. Run preflight and bring up Compose on an isolated host/VM.
2. Supply at least one real checklist `.xlsx` and map cells before pilot scoring.
3. Pin standard versions and document versions on each review run.
4. Keep human review in the loop; AI proposals are never auto-approval.
5. Measure precision/recall (or checklist agreement) only after real docs + templates are in use.
6. Back up Postgres + uploads + exports + Qdrant before pilot (see [backup-restore.md](backup-restore.md)).

## Technical gaps

- Live Compose e2e may be blocked in CI/agent VMs without Docker.
- OCR path records `OCR_NEEDED` — no OCR engine bundled in v1.
- VBA / macro-heavy `.xlsm` features are not executed; prefer openpyxl-safe templates.
- Cross-document SECI quality depends on pinned peers and extractable units.
- Concurrent Ollama calls capped at 1.
