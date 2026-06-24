# VERBICARE Knowledge Base

Last updated: 2026-05-30

## Overview

VERBICARE is an AI call audit platform for collections and sales QA. Stack: Flask backend (`care-backend`), React/Vite dashboard (`care-dashboard`). Production: EC2 + RDS Postgres + S3, frontend at `care.verbilab.com`.

---

## 1. Collections QA

**Status:** Active — default audit mode (`CARE_DEFAULT_AUDIT_MODE=collections`).

**Flow:** Upload → Sarvam STT → labelled transcript → LLM/rules scoring → summary + insights → dashboard/reports.

**Scoring framework (20 pts):** A1 Opening through A9 Troubleshooting. Key compliance: RPC before disclosure, PTP rules (amount + date + mode), third-party handling.

**Files:**
- `care-backend/processor.py` — pipeline + collections prompt (`SCORING_PROMPT`)
- `care-backend/audit_modes/collections.py` — collections mode wrapper
- `care-backend/scoring_rules.py` — rules fallback + KPI detection

**Env:** `SARVAM_API_KEY` required for LLM scoring; `CARE_RULES_ONLY_SCORING=1` skips LLM (dev only).

---

## 2. Sales QA

**Status:** Logic added — target completion Tuesday.

**Activation:**
- Set `CARE_DEFAULT_AUDIT_MODE=sales`, or
- Upload with form field `audit_mode=sales`, or
- Set `campaign_id` containing `sales`.

**Scoring framework (24 pts):**
| Parameter | Focus |
|-----------|--------|
| S1 Greeting | Rapport, intro, purpose |
| S2 Product explanation | Value prop, benefits |
| S3 Objection handling | Acknowledge, reframe |
| S4 Compliance script | Disclosures, no false claims |
| S5 Lead qualification | BANT-style discovery |
| S6 Closing quality | Next steps, recap |
| S7 Customer sentiment | Empathy, listening |
| S8 Conversion probability | Outcome likelihood |

**Files:** `care-backend/audit_modes/sales.py`, `audit_modes/__init__.py`

Collections and sales prompts are separate and configurable via audit mode resolution in `processor._resolve_audit_mode()`.

---

## 3. LeadSquared CRM Integration

**Status:** Pipeline scaffold — webhook + push placeholder (not live until credentials configured).

**Goal:** Sales live calls audited by VERBICARE; audit summary, score, compliance insights, and recommendations pushed to LeadSquared.

**Structure:**
```
care-backend/integrations/
  crm/
    base_crm.py      # Generic CRM interface
    leadsquared.py   # LeadSquared implementation
  dialer/
    base_dialer.py   # Future dialer webhooks
```

**Env vars** (see `.env.example`):
- `LEADSQUARED_API_BASE_URL`
- `LEADSQUARED_ACCESS_KEY`
- `LEADSQUARED_SECRET_KEY`
- `LEADSQUARED_WEBHOOK_SECRET`

**Endpoints:**
- `POST /api/v1/integrations/leadsquared/webhook` — inbound call events (placeholder)
- Future: post-audit hook calls `LeadSquaredCRM.push_audit_result()`

**Lead/call mapping:** `lead_id`, `call_id` extracted from webhook payload (`LeadId`, `CallId`, etc.).

---

## 4. LeadSquared Usage Tracking

**Status:** Implemented — `crm_usage_logs` table + admin API.

**Tracked fields:** endpoint, timestamp, status code, success/failure, call/lead ID, org ID, sync attempts, duration (ms).

**Admin route:** `GET /api/v1/admin/crm-usage` (requires `manage_settings` permission).

**Dashboard:** Settings → Integrations → CRM Usage Metrics (or `/admin/crm-usage`).

---

## 5. Generic CRM/Dialer Framework

New CRMs implement `BaseCRM` (`is_configured`, `push_audit_result`, `handle_webhook`). New dialers implement `BaseDialer`. LeadSquared is the first CRM adapter; no LeadSquared-specific code in core audit pipeline.

---

## 6. Ollama Voicebot Feasibility

See [OLLAMA_VOICEBOT_FEASIBILITY.md](./OLLAMA_VOICEBOT_FEASIBILITY.md). Documentation only — no voicebot implementation in this release.

---

## 7. Local Development (Windows)

```powershell
# Backend
cd care-backend
.\.venv\Scripts\Activate.ps1
python app.py

# Frontend
cd care-dashboard
npm run dev
```

Frontend proxies `/api` → `localhost:5000` via Vite. Do not use gunicorn on Windows.

---

## 8. Deployment Notes

- **Backend:** EC2 + gunicorn; restart after pull + `pip install -r requirements.txt`
- **Frontend:** Amplify/Netlify with `VITE_API_URL=https://api.care.verbilab.com`
- Never commit `.env` or secrets
- CORS: `CARE_CORS_ORIGINS` if restricting origins

---

## 9. User Management / RBAC

Roles: `super_admin`, `admin`, `qa_manager`, `team_leader`, `read_only`.

Permissions defined in `care-backend/permissions.py`. Admin Users page: `/admin/users` (`manage_users` permission).

OTP login default; password login gated by `AUTH_PASSWORD_ENABLED=false`.
