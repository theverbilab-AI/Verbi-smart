# VERBICARE Security Audit — Demo Readiness

Last updated: 2026-06-23

## Summary

VERBICARE uses JWT auth, server-side RBAC, and environment-based secrets. Suitable for controlled demo and staged production with the recommendations below.

---

## Authentication

| Control | Status | Notes |
|---------|--------|-------|
| JWT (HS256) | ✅ | 12h expiry; `JWT_SECRET` in `.env` only |
| OTP login (AWS SES) | ✅ | Sandbox limits — verify recipient emails for demo |
| Password login | ⚙️ | Gated by `AUTH_PASSWORD_ENABLED` |
| Session bootstrap | ✅ | `/api/auth/me` on app load |
| Logout | ✅ | Clears `care_token` + `care_user` |

**Recommendation:** Rotate `JWT_SECRET` per environment; use RS256 + short TTL for national-scale prod.

---

## Authorization (RBAC)

| Control | Status |
|---------|--------|
| `require_auth` on protected routes | ✅ |
| `require_permission()` on admin routes | ✅ |
| Backend enforces self-delete/disable block | ✅ |
| Backend enforces own `manage_users` retention | ✅ |
| Frontend `RequirePerm` route gates | ✅ |

Permissions: `dashboard_view`, `upload_calls`, `view_reports`, `export_reports`, `manage_users`, `manage_settings`, `view_call_details`, `delete_calls`, `compliance_flags`, `agent_performance`, `crm_usage`.

---

## CORS

- Configured via `CARE_CORS_ORIGINS` (comma-separated).
- Default `*` for dev; **set explicit origins in production** (`https://care.verbilab.com`).

---

## Input validation

| Area | Status |
|------|--------|
| Email format (OTP, profile, users) | ✅ |
| Role whitelist | ✅ |
| Permission whitelist | ✅ |
| Duplicate email check | ✅ |
| Upload file extensions | ✅ |
| JSON error responses | ✅ |

---

## Secrets

| Rule | Status |
|------|--------|
| No secrets in frontend bundle | ✅ `VITE_API_URL` only |
| `.env` gitignored | ✅ |
| `.env.example` without real keys | ✅ |
| LeadSquared/AWS via env | ✅ |

**Action:** Never commit `care-backend/.env`; rotate SES SMTP if exposed.

---

## Admin routes (protected)

- `GET/POST/PATCH/DELETE /api/admin/users/*`
- `GET /api/v1/admin/crm-usage`
- `POST /api/v1/integrations/crm/*/push/*`
- `POST /api/v1/admin/purge-calls`

All require JWT + `manage_users` or `crm_usage` as applicable.

---

## Upload security

- Auth required on `/api/v1/calls/ingest`
- Extension allowlist
- Files stored outside web root (`uploads/` + optional S3)
- Max size enforced client-side; add server limit for prod

---

## Error handling

- API returns JSON `{ error, detail? }` — no stack traces to client in production
- `FLASK_ENV=production` disables OTP dev expose (unless `DEBUG=true`)

---

## Recommendations before national-scale launch

1. **Rate limiting** — Add Flask-Limiter or API Gateway limits on `/api/auth/otp/send` (60s cooldown exists; add IP limits).
2. **HTTPS only** — Enforce TLS on EC2/nginx; HSTS headers.
3. **SES production access** — Exit sandbox for arbitrary recipient OTP.
4. **Audit logging** — Admin actions to `audit_logs` table (future).
5. **WAF** — CloudFront/AWS WAF in front of API.
6. **DB backups** — RDS automated backups verified.
7. **Dependency scan** — `pip audit` / `npm audit` in CI.

---

## Demo checklist (security)

- [ ] `JWT_SECRET` unique on demo server
- [ ] `CARE_CORS_ORIGINS` set to frontend URL only
- [ ] `AUTH_OTP_DEV_EXPOSE=false` in prod
- [ ] Demo user emails verified in SES
- [ ] No `.env` in git status
