"""
CARE login OTP — AWS SES (Simple Email Service).

Env (pick one transport):
  A) SMTP (from SES console → SMTP settings):
     AWS_SES_REGION=us-east-1
     SES_SMTP_USERNAME=AKIA...
     SES_SMTP_PASSWORD=...
  B) boto3 API (IAM access key with ses:SendEmail):
     AWS_ACCESS_KEY_ID=...
     AWS_SECRET_ACCESS_KEY=...

  SES_FROM_EMAIL=theverbilab@gmail.com
  OTP_EXPIRY_MINUTES=5
  AUTH_OTP_ENABLED=true
"""

from __future__ import annotations

import hashlib
import hmac
import os
import random
import re
import smtplib
from datetime import datetime, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

SES_SMTP_HOSTS = {
    "us-east-1": "email-smtp.us-east-1.amazonaws.com",
    "us-east-2": "email-smtp.us-east-2.amazonaws.com",
    "us-west-1": "email-smtp.us-west-1.amazonaws.com",
    "us-west-2": "email-smtp.us-west-2.amazonaws.com",
    "eu-west-1": "email-smtp.eu-west-1.amazonaws.com",
    "eu-north-1": "email-smtp.eu-north-1.amazonaws.com",
    "ap-south-1": "email-smtp.ap-south-1.amazonaws.com",
}


def _ses_region() -> str:
    return (os.getenv("AWS_SES_REGION") or os.getenv("AWS_REGION") or "us-east-1").strip()


def _smtp_configured() -> bool:
    return bool(
        (os.getenv("SES_SMTP_USERNAME") or os.getenv("AWS_SES_SMTP_USERNAME") or "").strip()
        and (os.getenv("SES_SMTP_PASSWORD") or os.getenv("AWS_SES_SMTP_PASSWORD") or "").strip()
    )


def otp_enabled() -> bool:
    return os.getenv("AUTH_OTP_ENABLED", "true").strip().lower() in {"1", "true", "yes"}


def ses_configured() -> bool:
    from_email = (os.getenv("SES_FROM_EMAIL") or "").strip()
    if not from_email:
        return False
    if _smtp_configured():
        return True
    if os.getenv("AWS_ACCESS_KEY_ID") and os.getenv("AWS_SECRET_ACCESS_KEY"):
        return True
    try:
        import boto3
        boto3.client("ses", region_name=_ses_region())
        return True
    except Exception:
        return False


def _from_address() -> str:
    """Display name + email improves inbox placement vs bare Gmail address."""
    addr = (os.getenv("SES_FROM_EMAIL") or "theverbilab@gmail.com").strip()
    name = (os.getenv("SES_FROM_NAME") or "Verbilab CARE").strip()
    if name and "<" not in addr:
        return f"{name} <{addr}>"
    return addr


def _reply_to() -> str | None:
    r = (os.getenv("SES_REPLY_TO") or os.getenv("SES_FROM_EMAIL") or "").strip()
    return r or None


def _build_email_bodies(code: str) -> tuple[str, str, str]:
    app_name = os.getenv("APP_NAME", "Verbilab CARE")
    mins = otp_expiry_minutes()
    # Avoid putting the OTP in the subject — spam filters flag that pattern.
    subject = os.getenv("SES_OTP_SUBJECT", f"Your {app_name} verification code")
    text_body = (
        f"Hello,\n\n"
        f"Use this verification code to sign in to {app_name}:\n\n"
        f"    {code}\n\n"
        f"This code expires in {mins} minutes. Do not share it with anyone.\n\n"
        f"If you did not try to sign in, you can safely ignore this email.\n\n"
        f"— Verbilab\n"
        f"Call Audit & Conduct Risk Engine (CARE)\n"
    )
    html_body = f"""<!DOCTYPE html>
<html lang="en">
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"></head>
<body style="margin:0;padding:0;background:#f3f4f6;font-family:system-ui,-apple-system,Segoe UI,sans-serif">
  <span style="display:none;max-height:0;overflow:hidden">Your sign-in code expires in {mins} minutes.</span>
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#f3f4f6;padding:32px 16px">
    <tr><td align="center">
      <table role="presentation" width="100%" style="max-width:480px;background:#ffffff;border-radius:12px;border:1px solid #e5e7eb;padding:32px 28px">
        <tr><td>
          <p style="margin:0 0 8px;font-size:13px;font-weight:600;color:#0891b2;letter-spacing:0.04em;text-transform:uppercase">Verbilab CARE</p>
          <h1 style="margin:0 0 12px;font-size:22px;font-weight:700;color:#111827">Sign-in verification</h1>
          <p style="margin:0 0 24px;font-size:15px;line-height:1.5;color:#4b5563">
            Enter this code on the CARE login page to continue:
          </p>
          <p style="margin:0 0 24px;font-size:34px;font-weight:700;letter-spacing:10px;color:#111827;text-align:center;font-family:ui-monospace,monospace">{code}</p>
          <p style="margin:0 0 8px;font-size:14px;color:#6b7280">Expires in <strong>{mins} minutes</strong>. Never share this code.</p>
          <p style="margin:24px 0 0;font-size:12px;line-height:1.5;color:#9ca3af;border-top:1px solid #f3f4f6;padding-top:16px">
            If you did not request this email, ignore it — your account stays secure.
          </p>
        </td></tr>
      </table>
      <p style="margin:16px 0 0;font-size:11px;color:#9ca3af">© Verbilab · Call Audit &amp; Conduct Risk Engine</p>
    </td></tr>
  </table>
</body>
</html>"""
    return subject, text_body, html_body


def _apply_email_headers(msg, to_email: str, from_display: str) -> None:
    msg["From"] = from_display
    msg["To"] = to_email
    reply = _reply_to()
    if reply:
        msg["Reply-To"] = reply
    msg["X-Auto-Response-Suppress"] = "OOF, AutoReply"
    msg["Auto-Submitted"] = "auto-generated"


def _send_via_smtp(to_email: str, from_display: str, subject: str, text_body: str, html_body: str) -> dict:
    region = _ses_region()
    host = (os.getenv("SES_SMTP_HOST") or "").strip() or SES_SMTP_HOSTS.get(region, f"email-smtp.{region}.amazonaws.com")
    port = int(os.getenv("SES_SMTP_PORT", "587"))
    user = (os.getenv("SES_SMTP_USERNAME") or os.getenv("AWS_SES_SMTP_USERNAME") or "").strip()
    password = (os.getenv("SES_SMTP_PASSWORD") or os.getenv("AWS_SES_SMTP_PASSWORD") or "").strip()
    envelope_from = (os.getenv("SES_FROM_EMAIL") or "theverbilab@gmail.com").strip()

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    _apply_email_headers(msg, to_email, from_display)
    msg.attach(MIMEText(text_body, "plain", "utf-8"))
    msg.attach(MIMEText(html_body, "html", "utf-8"))

    with smtplib.SMTP(host, port, timeout=30) as server:
        server.ehlo()
        server.starttls()
        server.ehlo()
        server.login(user, password)
        server.sendmail(envelope_from, [to_email], msg.as_string())

    return {"transport": "smtp", "host": host, "region": region, "from": from_display}


def _send_via_boto3(to_email: str, from_display: str, subject: str, text_body: str, html_body: str) -> dict:
    import boto3
    from botocore.exceptions import ClientError

    region = _ses_region()
    client = boto3.client("ses", region_name=region)
    dest: dict = {"ToAddresses": [to_email]}
    reply = _reply_to()
    try:
        kwargs: dict = {
            "Source": from_display,
            "Destination": dest,
            "Message": {
                "Subject": {"Data": subject, "Charset": "UTF-8"},
                "Body": {
                    "Text": {"Data": text_body, "Charset": "UTF-8"},
                    "Html": {"Data": html_body, "Charset": "UTF-8"},
                },
            },
        }
        if reply:
            kwargs["ReplyToAddresses"] = [reply]
        resp = client.send_email(**kwargs)
        return {"transport": "boto3", "message_id": resp.get("MessageId"), "region": region, "from": from_display}
    except ClientError as exc:
        err_code = exc.response.get("Error", {}).get("Code", "SES_ERROR")
        msg = exc.response.get("Error", {}).get("Message", str(exc))
        raise RuntimeError(f"SES {err_code}: {msg}") from exc


def send_login_otp_email(to_email: str, code: str) -> dict:
    """Send OTP via SES SMTP (preferred if creds set) or boto3 API."""
    from_display = _from_address()
    subject, text_body, html_body = _build_email_bodies(code)

    if _smtp_configured():
        return _send_via_smtp(to_email, from_display, subject, text_body, html_body)
    return _send_via_boto3(to_email, from_display, subject, text_body, html_body)


def _otp_secret() -> bytes:
    return (os.getenv("JWT_SECRET") or "care-otp-dev-secret").encode("utf-8")


def hash_otp_code(email: str, code: str) -> str:
    msg = f"{email.strip().lower()}:{code.strip()}"
    return hmac.new(_otp_secret(), msg.encode("utf-8"), hashlib.sha256).hexdigest()


def generate_otp_code(length: int | None = None) -> str:
    n = int(length or os.getenv("OTP_LENGTH", "6"))
    n = max(4, min(8, n))
    return "".join(str(random.SystemRandom().randint(0, 9)) for _ in range(n))


def otp_expiry_minutes() -> int:
    try:
        return max(1, min(30, int(os.getenv("OTP_EXPIRY_MINUTES", "5"))))
    except ValueError:
        return 5


def normalize_email(email: str) -> str:
    return (email or "").strip().lower()


def valid_email(email: str) -> bool:
    return bool(EMAIL_RE.match(normalize_email(email)))


def dev_expose_otp() -> bool:
    if os.getenv("AUTH_OTP_DEV_EXPOSE", "").strip().lower() in {"1", "true", "yes"}:
        return True
    return os.getenv("FLASK_ENV", "").lower() == "development" or os.getenv("DEBUG", "").lower() == "true"


def utcnow() -> datetime:
    return datetime.now(timezone.utc)
