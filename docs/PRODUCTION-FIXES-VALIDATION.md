# Production Fixes — Validation Report (June 2026)

## Priority 1: Calls not getting audited

### Root cause
1. **Daemon worker threads lost** — `process_call_async` runs in a background thread; Flask dev reloader or server restart kills in-flight work, leaving calls stuck in `queued` / `transcribing`.
2. **Recovery marked failed instead of retrying** — `recover_stuck_calls()` only re-scored `scoring` calls with a transcript; other stuck calls were set to `failed` after 3–8 minutes without re-queueing.
3. **No structured pipeline log** — failures were hard to diagnose from status alone.

### Fix
- `audit_pipeline.py` — append `analysis.pipeline_log` on each stage (`fetching_started`, `transcribing_started`, `scoring_started`, `processed`, `pipeline_error`).
- `recover_stuck_calls()` — re-queue calls in `queued`/`fetching`/`transcribing` when audio path exists (up to `CARE_MAX_PIPELINE_RETRIES`, default 3).
- `app.py` — background watchdog every 120s (`CARE_PIPELINE_WATCHDOG=1`).

### How to verify
```powershell
# After upload, inspect pipeline log on a call:
curl -H "Authorization: Bearer $TOKEN" https://care.verbilab.com/api/v1/calls/CALL-XXXX
# → analysis.pipeline_log[], analysis.pipeline_last_event
```

---

## Priority 2: LANGUAGE_ISSUE false positive

### Root cause
- Disposition rule matched bare substring **`"language"`** on the **full transcript** (including agent disclaimer), causing false `LANGUAGE_ISSUE` when no customer language barrier existed.
- Ritika-style calls with **app download problems** were not mapped to `APP_ISSUE`.

### Fix (`scoring_rules.py`)
- Language barrier phrases require **customer utterances only** (word-boundary matching).
- Removed bare `"language"` / `"hindi nahi"` short matches from agent-side scan.
- Added app-download phrases (`app is not downloading`, `not downloading`, …).
- `score_transcript()` forces final `resolve_disposition()` from rules (LLM cannot override).

### Tests
```powershell
cd care-backend
python scripts/test_production_fixes.py
# All production fix tests passed.
```

---

## Priority 3: Demo KPI scoring /10

### Config (revert anytime)
| Layer | Variable | Demo value |
|-------|----------|------------|
| Dashboard | `VITE_KPI_DISPLAY_MAX=10` | Show P1=/10, P2=/10, … |
| Backend CSV | `CARE_KPI_DISPLAY_MAX=10` | Export scaled scores |

Internal DB scores unchanged (still native /2, /3, /1). Display scales proportionally.

---

## Priority 4: Hide KPI names (P1, P2, …)

### Config
| Layer | Variable |
|-------|----------|
| Dashboard | `VITE_KPI_MASK_CLIENT_NAMES=1` |
| Backend CSV | `CARE_KPI_MASK_NAMES=1` |

### Applied to
- Call detail score breakdown
- Live AI Audit opening checklist
- KPI Tracker table headers
- Reports page CSV export
- Backend bulk CSV export
- Sales KPI tracker (P1–P15)

Internal keys (`A1_opening`, `opening`, etc.) unchanged in DB/API.

---

## Files changed

### Backend
- `audit_pipeline.py` (new)
- `client_display.py` (new)
- `processor.py` — pipeline logging, recovery retry, CSV masking, disposition override
- `scoring_rules.py` — language / app-issue rules
- `app.py` — pipeline watchdog
- `.env.example` — new vars
- `scripts/test_production_fixes.py` (new)

### Dashboard
- `src/config/qaDisplay.js` (new)
- `src/utils/kpiMetrics.js`
- `src/utils/salesMetrics.js`
- `src/pages/CallDetailPage.jsx`
- `src/pages/KpiTrackerPage.jsx`
- `src/pages/ReportsPage.jsx`
- `src/components/LiveAiAudit.jsx`

---

## Deploy checklist

1. **Backend EC2** — pull, restart gunicorn/flask; optional `.env`:
   ```
   CARE_PIPELINE_WATCHDOG=1
   CARE_KPI_DISPLAY_MAX=10
   CARE_KPI_MASK_NAMES=1
   ```
2. **Dashboard** — rebuild with `care-dashboard/.env`:
   ```
   VITE_KPI_DISPLAY_MAX=10
   VITE_KPI_MASK_CLIENT_NAMES=1
   ```
3. **Reprocess** Ritika call (`CALL-C54684E0`) via dashboard Reprocess to refresh disposition after language fix.

---

## Regression (Priority 5)

Run when `SARVAM_API_KEY` is set:
```powershell
cd care-backend
python scripts/e2e_local_test.py
```

Unit tests (no API):
```powershell
python scripts/test_production_fixes.py
```
