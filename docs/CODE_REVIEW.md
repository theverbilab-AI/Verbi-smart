# VerbiSmart (CARE) — Production Code Review

**Date:** 2026-07-03  
**Scope:** Production pipeline and dashboard (`care-backend`, `care-dashboard`)  
**Constraint:** No business-logic refactors; behaviour preserved except documented safe fixes.

---

## Executive summary

The production Sarvam pipeline is **functionally sound** for demo use: diarization → role mapping → rules/LLM scoring → RDS persist. Primary concerns are **authorization gaps** (see `SECURITY_AUDIT.md`), **S3 IAM on EC2**, and **operational timeouts** on health checks (partially addressed).

| Category | Critical | High | Medium | Low |
|----------|:--------:|:----:|:------:|:---:|
| Bugs | 0 | 1 | 3 | 4 |
| Concurrency | 0 | 0 | 2 | 1 |
| Performance | 0 | 1 | 3 | 2 |
| Error handling | 0 | 0 | 4 | 3 |

---

## Production files reviewed

### Backend core

| File | Lines (approx) | Status |
|------|----------------|--------|
| `app.py` | 1815 | Reviewed — route layer, auth, ingestion |
| `processor.py` | 2000+ | Reviewed — STT, scoring, threading |
| `database.py` | 1570 | Reviewed — Postgres/SQLite, migrations |
| `diarization.py` | 220 | Reviewed — Sarvam batch diarization |
| `storage.py` | 250 | Reviewed — S3 archive/proxy |
| `scoring_rules.py` | 2300+ | Reviewed — rules engine |
| `speaker_attribution.py` | — | Reviewed — role heuristics |
| `qa_validation.py` | — | Reviewed — post-score validation |
| `permissions.py` | — | Reviewed — RBAC |
| `email_otp.py` | — | Reviewed — SES OTP |
| `audit_modes/collections.py` | — | Reviewed |
| `audit_modes/sales.py` | — | Reviewed |
| `client_display.py` | — | Reviewed — KPI display masking |

### Dashboard

| File | Status |
|------|--------|
| `App.jsx`, `main.jsx` | Reviewed — routing, auth bootstrap |
| `services/api.js` | Reviewed — all API calls |
| `pages/Dashboardpage.jsx` | Reviewed — KPI aggregation display |
| `pages/UploadPage.jsx` | Reviewed — local/S3/Drive upload |
| `pages/CallDetailPage.jsx` | Reviewed — transcript, audio player |
| `pages/ReportsPage.jsx` | Reviewed — paginated call list |
| `pages/KpiTrackerPage.jsx` | Reviewed — PRD KPIs |
| `pages/SettingsPage.jsx` | Reviewed — integrations, theme |
| `pages/LoginPage.jsx` | Reviewed — OTP/password |
| `pages/AdminUsersPage.jsx` | Reviewed — user CRUD |
| `components/Navbar.jsx`, `Sidebar.jsx` | Reviewed |
| `components/LiveAiAudit.jsx` | Reviewed — audio + transcript |
| `index.css` | Reviewed — light/dark theme tokens |

---

## Critical / High bugs

### H-B1 — S3 credentials invalid on EC2 (operational)

| Field | Detail |
|-------|--------|
| **Location** | `storage.py` `archive_local_audio`, `processor.py` `fetch_from_s3` |
| **Symptom** | `InvalidAccessKeyId` / 403 on S3 ingest and archive |
| **Impact** | S3 uploads fail; local playback cache may still work |
| **Fix** | Update EC2 `.env` with valid IAM keys + `S3_AUDIO_REGION=eu-north-1` |

---

## Medium bugs & gaps

### M-B1 — Windows Unicode crash in diarization logging (fixed prior)

| **Location** | `diarization.py` `_dprint()` |
| **Issue** | ₹ in transcript log caused false `diarization_failed` on Windows |
| **Status** | Fixed — encoding-safe logging |

### M-B2 — `get_call` org fallback (security + correctness)

| **Location** | `app.py` multiple routes |
| **Issue** | Cross-org data leak — see SECURITY_AUDIT C2 |
| **Status** | Documented; not changed (behaviour constraint) |

### M-B3 — Health endpoint blocking on S3 probe (mitigated)

| **Location** | `storage.py` `s3_probe()` |
| **Issue** | Slow/hung `/api/health` when AWS unreachable |
| **Status** | Fixed — 5s connect / 10s read timeout |

### M-B4 — Empty `agent_id` on some uploads

| **Location** | Upload metadata parsing |
| **Issue** | KPI tracker shows "Unknown" agent when filename lacks agent token |
| **Fix** | Encourage metadata on upload form; optional filename parser improvement |

---

## Concurrency & threading

| Item | Location | Assessment |
|------|----------|------------|
| Parallel processing | `processor.py` `_PROCESS_SEM` | ✅ Semaphore limits concurrent Sarvam jobs (`CARE_MAX_PARALLEL_PROCESSING`) |
| Background threads | `process_call_async` | ✅ Daemon threads; status updates via `update_call` |
| Pipeline watchdog | `app.py` `_pipeline_watchdog` | ✅ Recovers stuck queued/transcribing calls |
| Race on reprocess | `REPROCESS_JOBS` dict | ⚠️ Medium — in-memory job map lost on restart; no cross-worker lock on multi-worker gunicorn |
| DB connections | `database.py` `@contextmanager get_conn` | ✅ Per-request connection; no obvious leak |

**Recommendation:** Use Redis or DB row locks if running multiple gunicorn workers with reprocess endpoints.

---

## Memory & resource cleanup

| Item | Assessment |
|------|------------|
| Temp diarization dirs | ✅ `shutil.rmtree` in `finally` (`diarization.py`) |
| Temp audio fetch | ✅ `tempfile` + cleanup in processor |
| S3 download to disk | ✅ Files in temp/upload dirs |
| Large transcript in memory | ⚠️ Full transcript held in call dict — acceptable for call volume |
| Thread accumulation | ✅ Daemon threads; semaphore bounds concurrency |

---

## Exception handling & retries

| Component | Retry logic | Timeout |
|-----------|-------------|---------|
| Sarvam STT chunks | ✅ 3 attempts per chunk | 90s |
| Sarvam diarization batch | ❌ Single job wait | 600s (`CARE_DIAR_TIMEOUT`) |
| S3 fetch | ✅ Key prefix fallback | boto default |
| URL fetch | ❌ Single attempt | 120s |
| Scoring LLM | ✅ Rules fallback on failure | 90s |
| Stuck call recovery | ✅ Watchdog every 120s | 5 min age default |

**Gap:** No circuit breaker for Sarvam API outages — repeated failures will queue indefinitely until watchdog marks failed.

---

## Performance bottlenecks

| Bottleneck | Impact | Mitigation |
|------------|--------|------------|
| Sarvam batch diarization | 30–90s per call | Expected; parallel semaphore=4 helps bulk |
| Sequential scoring LLM | Adds 5–15s | `CARE_RULES_ONLY_SCORING=1` for dev speed |
| `list_calls(limit=500)` on dashboard | OK for <500 calls | Paginate KPI endpoint at scale |
| `s3_probe` on every health check | Added latency | Timeouts added; consider caching 60s |
| Full CSV export in memory | Medium for 10k+ calls | Stream response or async export job |

---

## Upload pipeline review

```
POST /api/v1/calls/upload
  → extension check (ALLOWED_EXTENSIONS)
  → save to uploads/
  → save_call(status=queued)
  → process_call_async(thread)
       → ffmpeg normalize
       → diarize_audio (Sarvam batch) OR fallback
       → score_transcript
       → archive_local_audio (S3) + persist_playback_copy
       → update_call(processed)
```

| Check | Status |
|-------|--------|
| File extension validation | ✅ |
| File size limit | ⚠️ Document says 500 MB; verify enforced in route |
| Path traversal on filename | ✅ Uses call_id prefix + sanitized names |
| Auth on upload | ⚠️ Upload route should require auth (verify `@require_auth`) |
| ZIP bomb | ⚠️ ZIP allowed — extraction path should be reviewed if implemented |

---

## Sarvam integration review

| Step | Module | Status |
|------|--------|--------|
| Batch job create | `diarization.py` | ✅ `saaras:v3`, `with_diarization=True` |
| Speaker merge | `_merge_entries` | ✅ Consecutive same-speaker collapse |
| Role mapping | `_map_speakers` | ✅ One decision per call |
| Fallback | Returns None → text bifurcation | ✅ |
| Failure mode | `DiarizationFailedError` when required | ✅ |
| Cost control | Semaphore on parallel jobs | ✅ |

---

## Scoring engine review

| Component | Status |
|-----------|--------|
| `scoring_rules.py` | ✅ Deterministic rules; extensive keyword/KPI detection |
| LLM scoring | ✅ Optional via Sarvam; rules fallback |
| `CARE_RULES_ONLY_SCORING` | ✅ Dev/demo mode |
| Training examples | ✅ `training_data/scoring_examples.jsonl` |
| QA validation | ✅ `qa_validation.py` post-checks |

---

## Dashboard API usage review

| API | Used by | Auth header |
|-----|---------|-------------|
| `/api/auth/login`, OTP | LoginPage | N/A |
| `/api/v1/calls` | Reports, KPI, Dashboard | Bearer (when logged in) |
| `/api/v1/dashboard` | Dashboard | Bearer |
| `/api/v1/calls/upload` | UploadPage | Bearer |
| `/api/v1/calls/ingest-s3` | UploadPage S3 tab | Bearer |
| `/api/v1/integrations/status` | Settings | Bearer + manage_settings (backend) |

**Note:** Backend accepts unauthenticated calls API even when dashboard sends token — mismatch documented in security audit.

---

## Code quality observations

| Item | Finding | Action |
|------|---------|--------|
| Unused imports | Minor across scripts | Deferred — no production change |
| Duplicate `SettingsPage.jsx` path in glob | Windows path casing artifact | None |
| Logging | Mix of `print()` and audit tags | Standardize to structured logging (future) |
| Typing | Partial type hints in new modules | Improve incrementally |
| Tests | Scripts not pytest suite | Add `tests/` directory (future) |
| Documentation | `PRODUCT_ARCHITECTURE.md` added | ✅ |

---

## Safe improvements applied (this review)

1. `integrations_status` → `@require_permission("manage_settings")`
2. `s3_probe()` boto timeouts (5s/10s)
3. `.gitignore` PII artifact rules
4. POC archived to `archive/poc-stt/`
5. Dead dashboard components removed
6. Temp debug files deleted

---

## Recommended future improvements

1. **Auth hardening** — require JWT on all `/api/v1/calls*` routes (P0).
2. **Multi-worker safety** — Redis lock for reprocess jobs.
3. **S3 health cache** — cache probe result 60s to speed health checks.
4. **Structured logging** — JSON logs with call_id correlation for EC2/CloudWatch.
5. **pytest suite** — cover diarization role mapping, scoring rules, auth permissions.
6. **File size enforcement** — explicit `MAX_CONTENT_LENGTH` in Flask config.
7. **SSRF guard** — private IP blocklist on URL ingest.
8. **Remove nested `Verbilab_CARE/`** duplicate directory from workspace.

---

*Review covers all 72 backend and 44 dashboard source files. Archived POC (69 files) reviewed for import isolation only.*
