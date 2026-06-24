"""LeadSquared CRM integration for VERBICARE sales audit pipeline."""

from __future__ import annotations

import os
from typing import Any

import requests

from integrations.crm.base_crm import BaseCRM


class LeadSquaredCRM(BaseCRM):
    """
    LeadSquared API client (placeholder structure — wire to LeadSquared REST APIs).

    Env vars (see .env.example):
      LEADSQUARED_API_BASE_URL
      LEADSQUARED_ACCESS_KEY
      LEADSQUARED_SECRET_KEY
      LEADSQUARED_WEBHOOK_SECRET
    """

    provider_name = "leadsquared"

    def __init__(self, org_id: str = "org_default"):
        super().__init__(org_id=org_id)
        self.base_url = (
            (os.getenv("LEADSQUARED_BASE_URL") or os.getenv("LEADSQUARED_API_BASE_URL") or "")
            .strip()
            .rstrip("/")
        )
        self.access_key = (os.getenv("LEADSQUARED_ACCESS_KEY") or "").strip()
        self.secret_key = (os.getenv("LEADSQUARED_SECRET_KEY") or "").strip()
        self.webhook_secret = (os.getenv("LEADSQUARED_WEBHOOK_SECRET") or "").strip()

    def is_configured(self) -> bool:
        return bool(self.base_url and self.access_key and self.secret_key)

    def _auth_params(self) -> dict[str, str]:
        return {"accessKey": self.access_key, "secretKey": self.secret_key}

    def map_call_to_lead(self, payload: dict[str, Any]) -> tuple[str | None, str | None]:
        """Extract lead_id and call_id from webhook or dialer payload."""
        lead_id = (
            payload.get("lead_id")
            or payload.get("LeadId")
            or payload.get("ProspectID")
            or payload.get("prospect_id")
        )
        call_id = (
            payload.get("call_id")
            or payload.get("CallId")
            or payload.get("ActivityId")
            or payload.get("recording_id")
        )
        return (str(lead_id) if lead_id else None, str(call_id) if call_id else None)

    def handle_webhook(self, payload: dict[str, Any], headers: dict[str, str] | None = None) -> dict[str, Any]:
        headers = headers or {}
        if self.webhook_secret:
            token = headers.get("X-LeadSquared-Secret") or headers.get("x-leadsquared-secret") or ""
            if token != self.webhook_secret:
                self._log_usage(
                    endpoint="/webhook/inbound",
                    success=False,
                    status_code=401,
                    error_message="Invalid webhook secret",
                )
                return {"accepted": False, "error": "Unauthorized webhook"}

        lead_id, call_id = self.map_call_to_lead(payload)
        self._log_usage(
            endpoint="/webhook/inbound",
            call_id=call_id,
            lead_id=lead_id,
            success=True,
            status_code=202,
        )

        # Phase 2: enqueue audio URL → VERBICARE audit → push_audit_result
        return {
            "accepted": True,
            "provider": self.provider_name,
            "lead_id": lead_id,
            "call_id": call_id,
            "message": "Webhook received — audit pipeline placeholder (configure audio ingest next).",
        }

    def push_audit_result(
        self,
        *,
        lead_id: str,
        call_id: str,
        audit_payload: dict[str, Any],
    ) -> dict[str, Any]:
        """
        Push audit summary to LeadSquared activity/lead note.
        Uses LeadSquared LeadActivity / Custom API pattern (placeholder endpoint).
        """
        if not self.is_configured():
            self._log_usage(
                endpoint="/LeadManagement.svc/Activity.Create",
                call_id=call_id,
                lead_id=lead_id,
                success=False,
                status_code=503,
                error_message="LeadSquared not configured",
            )
            return {"ok": False, "error": "LeadSquared credentials not configured"}

        body = {
            "RelatedProspectId": lead_id,
            "ActivityEvent": 205,
            "ActivityNote": audit_payload.get("summary") or "",
            "Fields": [
                {"SchemaName": "mx_Custom_1", "Value": str(audit_payload.get("score_pct", ""))},
                {"SchemaName": "mx_Custom_2", "Value": ", ".join(audit_payload.get("compliance_flags") or [])},
                {"SchemaName": "mx_Custom_3", "Value": audit_payload.get("ai_suggestion") or ""},
            ],
            "VerbicareCallId": call_id,
        }

        def _post():
            url = f"{self.base_url}/LeadManagement.svc/Activity.Create"
            r = requests.post(url, params=self._auth_params(), json=body, timeout=30)
            return {"ok": r.status_code < 400, "status_code": r.status_code, "body": r.text[:500]}

        return self._timed_request(_post, endpoint="/LeadManagement.svc/Activity.Create", call_id=call_id, lead_id=lead_id)
