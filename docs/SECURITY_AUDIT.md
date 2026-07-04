# VerbiSmart (CARE) — Security Audit

**Date:** 2026-07-03  
**Scope:** Full repository review (`care-backend`, `care-dashboard`, deploy configs, archived POC)  
**Method:** Static analysis, grep for secrets, route/auth review, subprocess/SSRF/CORS audit  
**Production behaviour:** Not modified except two safe hardening changes (see § Positive changes)

---

## Executive summary

| Severity | Count |
|----------|------:|
| Critical | 3 |
| High | 4 |
| Medium | 8 |
| Low | 6 |

**No hardcoded live API keys, AWS credentials, HF tokens, or SSH private keys were found in tracked source files.**

The highest risk is **optional authentication on call/data routes** combined with **cross-org `get_call` fallback** and **unauthenticated audio streaming**. These are pre-existing design choices that must be addressed before external exposure beyond trusted QA users.

---

## Critical issues

### C1 — Unauthenticated access to call data (PII)

| Field | Detail |
|-------|--------|
| **Location** | `care-backend/app.py` — `GET /api/v1/calls`, `GET /api/v1/calls/<id>`, dashboard, reports, exports (~1169–1776) |
| **Finding** | Routes do not require `@require_auth`. `get_org_id()` falls back to `"org_default"` when JWT is absent. |
| **Impact** | Unauthenticated callers can list/read call transcripts, loan IDs, agent names, scores, and export CSV. |
| **Fix** | Add `@require_auth` to all data routes; reject unauthenticated requests with 401. |

### C2 — Cross-tenant IDOR via `get_call` fallback

| Field | Detail |
|-------|--------|
| **Location** | `care-backend/app.py` — e.g. lines ~1213, 1228, 1552–1554 |
| **Finding** | Pattern `get_call(call_id, org_id=org_id) or get_call(call_id)` bypasses org scoping. |
| **Impact** | User in org A (or unauthenticated caller with guessed `CALL-XXXXXXXX` id) can access other orgs' calls. |
| **Fix** | Remove bare `get_call(call_id)` fallback; enforce org match; return 404 on mismatch. |

### C3 — Unauthenticated audio streaming

| Field | Detail |
|-------|--------|
| **Location** | `care-backend/app.py` — `GET /api/v1/calls/<call_id>/audio` (~1547–1656) |
| **Finding** | No auth required; accepts `?token=` query param but does not enforce valid session for streaming. |
| **Impact** | Customer call recordings exposed if call ID is guessed (~32-bit hex space). |
| **Fix** | Require auth + org scope; issue short-lived signed playback tokens instead of JWT in URL. |

---

## High issues

### H1 — Default JWT secret

| Field | Detail |
|-------|--------|
| **Location** | `care-backend/app.py:130` |
| **Finding** | `SECRET = os.getenv("JWT_SECRET", "care-secret-change-in-prod")` |
| **Impact** | Forged admin tokens if env unset in production. |
| **Fix** | Fail startup when default secret detected in `FLASK_ENV=production`. |

### H2 — Default seeded password

| Field | Detail |
|-------|--------|
| **Location** | `care-backend/database.py:561–584` |
| **Finding** | Seed users use password `care@2025` when bcrypt available. |
| **Impact** | Known credentials if password login enabled. |
| **Fix** | Disable seed passwords in production; force OTP-only or one-time reset. |

### H3 — SSRF via URL ingest

| Field | Detail |
|-------|--------|
| **Location** | `care-backend/processor.py:174–192`; `app.py` ingest-url + audio proxy |
| **Finding** | `requests.get(url)` with no private IP / metadata blocklist. |
| **Impact** | Server-side fetch of internal endpoints (169.254.169.254, localhost). |
| **Fix** | URL allowlist, block RFC1918/link-local, validate redirect targets. |

### H4 — Unauthenticated mutation routes

| Field | Detail |
|-------|--------|
| **Location** | `care-backend/app.py` — speaker correction, reprocess, training example append (~1219–1502) |
| **Finding** | Expensive Sarvam reprocessing and transcript mutation without auth. |
| **Impact** | DoS (Sarvam API cost) and data tampering. |
| **Fix** | `@require_auth` + permission checks on all mutation endpoints. |

---

## Medium issues

### M1 — Public health endpoint infrastructure disclosure

| **Location** | `care-backend/app.py` `/api/health`; `storage.py` `s3_probe()` |
| **Finding** | Returns `s3_ok`, `s3_region`, DB type without auth. Error strings include bucket/IAM hints. |
| **Fix** | Minimal public health (`status`, `db_ok` only); move S3 probe to admin-only route. |

### M2 — Integrations status permission gap (fixed)

| **Location** | `care-backend/app.py` `/api/v1/integrations/status` |
| **Finding** | Was `@require_auth` only; any logged-in user could read S3 bucket/region. |
| **Fix applied** | Now `@require_permission("manage_settings")`. |

### M3 — JWT in query string

| **Location** | `app.py` `_attach_playback_urls`; `care-dashboard/src/services/api.js` |
| **Finding** | Audio URLs include `?token=` — leaks via logs, Referer, browser history. |
| **Fix** | Header-only auth or scoped playback tokens. |

### M4 — CORS default `*`

| **Location** | `care-backend/app.py:30–34` |
| **Finding** | `CARE_CORS_ORIGINS` defaults to `*`. |
| **Fix** | Set `https://care.verbilab.com` only in production `.env`. |

### M5 — CRM webhook fail-open

| **Location** | `integrations/crm/leadsquared.py`; webhook routes |
| **Finding** | Webhooks accepted when `LEADSQUARED_WEBHOOK_SECRET` unset. |
| **Fix** | Reject webhooks in production if secret missing. |

### M6 — Admin privilege escalation paths

| **Location** | `app.py` admin user create/patch |
| **Finding** | `manage_users` can set arbitrary `org_id` and `super_admin` role. |
| **Fix** | Restrict org to actor's org; cap assignable roles below actor level. |

### M7 — Dry-run / trace artifacts contain PII

| **Location** | Deleted: `DRY_RUN_REPORT.json`, `PIPELINE_TRACE_REPORT.md`, `dry_run_live.log` |
| **Finding** | Real filenames, transcripts, customer dialogue in local artifacts. |
| **Fix applied** | Files deleted; `.gitignore` rules added. |

### M8 — No rate limiting

| **Location** | All API routes |
| **Finding** | No Flask-Limiter or nginx rate limits on login, upload, reprocess. |
| **Fix** | Add per-IP limits on auth and expensive endpoints. |

---

## Low issues

| ID | Location | Finding |
|----|----------|---------|
| L1 | `processor.py` subprocess ffmpeg | Uses list args (no shell=True) — good; ensure ffmpeg path trusted |
| L2 | Upload extension allowlist | `ALLOWED_EXTENSIONS` checked — zip/csv allowed; ensure zip bomb limits |
| L3 | Error responses | Some routes return `str(e)` in JSON — avoid stack traces in prod |
| L4 | `AUTH_AVAILABLE` false | Auth bypass to super_admin mock user in dev if PyJWT missing |
| L5 | `poc-stt/scripts/.poc-l4-instance.json` | May contain EC2 instance metadata — archived, gitignored |
| L6 | Dashboard `localStorage` JWT | Standard XSS token theft risk if XSS introduced — no XSS sinks found |

---

## Secrets scan results

| Pattern | Result |
|---------|--------|
| `SARVAM_API_KEY=...` in source | **Not found** (env-only) |
| `AWS_ACCESS_KEY_ID` / secrets in source | **Not found** |
| `HF_TOKEN` literal values | **Not found** (read from env in POC scripts only) |
| `sk-...` OpenAI-style keys | **Not found** |
| `AKIA...` AWS keys | **Not found** |
| `.env` committed | **Not found** (gitignored) |
| `.env.example` | Empty placeholders only ✅ |
| `.env.production` (dashboard) | `VITE_API_URL` only ✅ |
| SSH `*.pem` | **Not found** |

---

## Positive security controls

| Control | Status |
|---------|--------|
| Secrets in environment variables | ✅ |
| `.env` / `*.pem` gitignored | ✅ |
| Parameterized SQL (`?` / `%s`) in `database.py` | ✅ |
| bcrypt password hashing | ✅ |
| JWT HS256 with expiry | ✅ |
| RBAC permission system | ✅ |
| `@require_permission` on admin routes | ✅ |
| Upload extension allowlist | ✅ |
| S3 proxy playback (no browser CORS to bucket) | ✅ |
| Settings UI no longer shows fake API key | ✅ |
| Integrations status gated to `manage_settings` | ✅ (this audit) |
| `s3_probe()` timeouts prevent health hang | ✅ (this audit) |
| No `eval`/`exec` in production Python | ✅ |
| No `dangerouslySetInnerHTML` in dashboard | ✅ |
| ffmpeg subprocess without `shell=True` | ✅ |

---

## File-by-file review coverage

### care-backend (production)

| File | Reviewed | Notes |
|------|:--------:|-------|
| `app.py` | ✅ | Auth gaps, CORS, routes, uploads |
| `processor.py` | ✅ | SSRF, subprocess, threading, Sarvam |
| `database.py` | ✅ | SQL params, seed passwords |
| `diarization.py` | ✅ | Sarvam SDK, safe logging |
| `storage.py` | ✅ | S3 IAM, probe timeouts |
| `scoring_rules.py` | ✅ | No code execution |
| `speaker_attribution.py` | ✅ | Heuristics only |
| `permissions.py` | ✅ | RBAC definitions |
| `email_otp.py` | ✅ | SES, OTP hashing |
| `audit_*.py` | ✅ | Export/pipeline logging |
| `integrations/**` | ✅ | Webhook auth placeholder |
| `deploy/**` | ✅ | IAM policy templates, no secrets |
| `scripts/**` | ✅ | Ops/debug only, not imported |

### care-dashboard

| File | Reviewed | Notes |
|------|:--------:|-------|
| `services/api.js` | ✅ | JWT header, token in audio URL |
| `pages/*.jsx` | ✅ | No XSS sinks |
| `components/*.jsx` | ✅ | Auth gates via permissions |
| `utils/permissions.js` | ✅ | Client-side only (must match backend) |

### Archived POC (`archive/poc-stt/`)

| Reviewed | Notes |
|:--------:|-------|
| ✅ | Isolated from production imports; HF token read from env in shell scripts only |

---

## Recommended remediation priority

1. **P0 (before external demo):** C1, C2, C3 — mandatory auth + org scoping on all call routes and audio.
2. **P1:** H1, H2, H4 — JWT secret enforcement, remove default passwords, protect mutations.
3. **P2:** H3, M3, M4, M8 — SSRF blocklist, remove JWT from URLs, tighten CORS, rate limits.
4. **P3:** M1, M5, M6 — health endpoint trim, webhook secrets, admin role caps.

---

*Auditor: automated + manual static review. Re-run after auth hardening deploy.*
