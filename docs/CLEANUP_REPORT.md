# Repository Cleanup Report

**Date:** 2026-07-03  
**Scope:** Verbilab_CARE full repository  
**Constraint:** Production behaviour unchanged; business logic not refactored.

---

## Summary

| Action | Count |
|--------|------:|
| Files deleted (temp / dead code) | 5 |
| Files moved to `archive/poc-stt/` | ~69 |
| Files retained as production stubs | 1 (`poc-stt/README.md`) |
| `.gitignore` rules added | 6 |
| Safe code fixes (non-behavioural) | 3 |

---

## Phase 1 — Files Deleted

| File | Reason |
|------|--------|
| `care-backend/scripts/dry_run_live.log` | Debug log (~175 KB); contained pipeline output |
| `care-backend/scripts/DRY_RUN_REPORT.json` | Temporary dry-run output; contained call IDs/scores |
| `care-backend/scripts/PIPELINE_TRACE_REPORT.md` | Debug trace with customer dialogue snippets |
| `care-dashboard/src/components/Reportspage.jsx` | Dead code — unused duplicate of `pages/ReportsPage.jsx` |
| `care-dashboard/src/layouts/MainLayout.jsx` | Dead code — layout inlined in `App.jsx` |

---

## Phase 1 — Files Archived

All experimental POC content moved to **`archive/poc-stt/`** (gitignored, local only):

| Category | Examples |
|----------|----------|
| GPU / Whisper legacy | `legacy_whisper/poc_*.py`, `poc_gpu.py`, `poc_whisper_context.py` |
| IndicConformer STT | `stt_indicconformer.py`, `stt_modes.py`, `vad_silero.py` |
| Pyannote diarization | `diarization_pyannote.py` |
| Translation experiments | `translate_en.py`, `translate_sarvam.py`, `indictrans_worker.py` |
| Benchmark outputs | `sample_results/*.json`, `sample_results/*.md` (17 files) |
| L4/T4 scripts | `scripts/run_option_*_benchmark.sh`, `launch_l4.ps1`, `remote_l4_run.sh` |
| Test/debug scripts | `test_hf_tokens.py`, `debug_tokenizer.py`, etc. |

**Kept in repo:** `poc-stt/README.md` — pointer to archive location.

**Production sample retained:** `care-backend/training_data/scoring_examples.jsonl` (used by scoring pipeline).

---

## Phase 1 — Not Deleted (intentional)

| Path | Reason |
|------|--------|
| `care-backend/scripts/dry_run_bulk.py` | Production ops tool for demo prep |
| `care-backend/scripts/dry_run_status.py` | Ops status reporter |
| `care-backend/scripts/test_*.py` | Regression scripts (not imported by app) |
| `care-backend/scripts/trace_*.py` | Debug utilities for support |
| `care-backend/care.db` | Local SQLite (gitignored) |
| `care-backend/uploads/` | Cleared on disk where possible; `.gitkeep` retained |
| `Verbilab_CARE/` nested duplicate | **Manual review recommended** — nested git repo; not auto-deleted |

---

## Phase 1 — `.gitignore` Updates

Added rules to prevent re-committing sensitive/temporary artifacts:

```
**/*.log
care-backend/scripts/DRY_RUN_REPORT.json
care-backend/scripts/PIPELINE_TRACE_REPORT.md
care-backend/scripts/E2E_LOCAL_REPORT.md
poc-stt/**
!poc-stt/README.md
```

---

## Safe Improvements Applied (no business-logic change)

| File | Change |
|------|--------|
| `care-backend/app.py` | `/api/v1/integrations/status` now requires `manage_settings` permission |
| `care-backend/storage.py` | `s3_probe()` uses 5s/10s boto timeouts (prevents `/api/health` hang) |
| `poc-stt/README.md` | Archive pointer for POC lab |

---

## Files Reviewed (inventory)

| Area | Files reviewed |
|------|----------------|
| `care-backend/` | 72 source/deploy files |
| `care-dashboard/src/` | 44 JS/JSX/CSS files |
| `docs/` | 5 markdown files |
| `poc-stt/` → archive | 69 archived files |
| Root config | `.gitignore`, `amplify.yml`, `README.md`, `.github/workflows/` |

**Total indexable production + config files reviewed:** ~125  
**Archived POC files reviewed:** ~69  

---

## Recommended Future Cleanup

1. Remove nested `Verbilab_CARE/` duplicate directory after confirming no unique commits.
2. Consolidate `care-backend/scripts/test_*.py` into a `tests/` folder with pytest.
3. Add pre-commit hook to block `*.log`, `DRY_RUN_*`, and `.env` commits.
4. Rotate AWS/Sarvam keys that appeared in historical logs/chat.
5. Purge `care-backend/uploads/` on EC2 before client demo (retain S3 archive only).
