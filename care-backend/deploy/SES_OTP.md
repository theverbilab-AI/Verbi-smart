# CARE Mail OTP — AWS SES setup

## 1. Verify sender in SES (us-east-1)

1. AWS Console → **Amazon SES** → **Configuration** → **Identities**
2. **Create identity** → **Email address** → `theverbilab@gmail.com`
3. Open the verification email and click the link → status **Verified**

> Sandbox mode: you must also **verify each recipient email** that will receive OTPs,  
> OR request **production access** (SES → Get set up → Request production access).

## 2. IAM / SMTP credentials

**Option A — SMTP (what you created in SES console):**

```env
AWS_SES_REGION=us-east-1
SES_FROM_EMAIL=theverbilab@gmail.com
SES_SMTP_USERNAME=AKIA...        # SMTP user name from CSV
SES_SMTP_PASSWORD=...            # SMTP password from CSV (not IAM secret key)
```

Host is auto: `email-smtp.us-east-1.amazonaws.com` port `587`.

**Option B — boto3 API** (separate IAM programmatic access key with `ses:SendEmail`):

```env
AWS_ACCESS_KEY_ID=...
AWS_SECRET_ACCESS_KEY=...
```

Never commit credentials to git. Store only in ECS/Railway env or AWS Secrets Manager.
If SMTP password was exposed in chat/screenshots, rotate it in SES → SMTP settings → Create SMTP credentials.

## 3. Environment variables (ECS / Railway)

```env
AWS_SES_REGION=us-east-1
SES_FROM_EMAIL=theverbilab@gmail.com
AUTH_OTP_ENABLED=true
OTP_EXPIRY_MINUTES=5
AWS_ACCESS_KEY_ID=...
AWS_SECRET_ACCESS_KEY=...
```

## 4. API endpoints

| Method | Path | Body |
|--------|------|------|
| POST | `/api/auth/otp/send` | `{ "email": "user@company.ai" }` |
| POST | `/api/auth/otp/verify` | `{ "email": "...", "code": "123456" }` |
| POST | `/api/auth/login` | password login (unchanged) |

## 5. Health check

`GET /api/health` returns:

```json
{
  "ses_configured": true,
  "otp_login": true,
  "ses_from": "theverbilab@gmail.com"
}
```

## 6. User must exist in DB

OTP only works for emails already registered in `users` (via super_admin `/api/auth/register` or seed).

Default dev user: `admin@care.ai` / `care@2025`

## 7. Domain verification (optional, later)

For `noreply@verbilab.com`, verify domain `verbilab.com` in SES and add DNS records, then set:

```env
SES_FROM_EMAIL=noreply@verbilab.com
```
