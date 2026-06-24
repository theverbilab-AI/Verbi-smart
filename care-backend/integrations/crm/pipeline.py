"""CRM audit pipeline: webhook → audit → push results back to CRM."""

from __future__ import annotations

from typing import Any

from integrations.crm.registry import get_crm


def receive_call_webhook(
    provider: str,
    payload: dict[str, Any],
    *,
    org_id: str = "org_default",
    headers: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Step 1: Inbound dialer/CRM webhook (queue audit)."""
    crm = get_crm(provider, org_id)
    return crm.handle_webhook(payload, headers=headers)


def build_audit_payload(call: dict[str, Any]) -> dict[str, Any]:
    """Normalize VERBICARE call row for CRM push."""
    analysis = call.get("analysis") or {}
    if isinstance(analysis, str):
        try:
            import json
            analysis = json.loads(analysis)
        except Exception:
            analysis = {}
    sales_kpi = analysis.get("sales_kpi") or {}
    return {
        "call_id": call.get("id"),
        "score": call.get("score"),
        "score_pct": call.get("score_pct"),
        "grade": call.get("grade"),
        "summary": call.get("summary") or "",
        "disposition": call.get("disposition"),
        "compliance_flags": call.get("compliance_flags") or [],
        "ai_suggestion": call.get("ai_suggestion") or "",
        "intent": sales_kpi.get("intent") or "",
        "conversion_probability": sales_kpi.get("conversion_probability") or call.get("conversion_probability"),
        "sales_kpi": sales_kpi,
        "audit_mode": analysis.get("audit_mode") or "collections",
    }


def push_audit_to_crm(
    provider: str,
    *,
    call_id: str,
    lead_id: str,
    org_id: str = "org_default",
) -> dict[str, Any]:
    """Step 3: Push completed audit to CRM."""
    from database import get_call

    call = get_call(call_id)
    if not call:
        return {"ok": False, "error": "Call not found", "status_code": 404}
    if call.get("status") != "processed":
        return {"ok": False, "error": "Call audit not complete", "status_code": 409}
    crm = get_crm(provider, org_id)
    payload = build_audit_payload(call)
    return crm.push_audit_result(lead_id=lead_id, call_id=call_id, audit_payload=payload)
