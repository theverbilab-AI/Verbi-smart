"""Abstract CRM integration interface for VERBICARE."""

from __future__ import annotations

import time
from abc import ABC, abstractmethod
from typing import Any


class BaseCRM(ABC):
    """Base class for CRM providers (LeadSquared, Salesforce, HubSpot, etc.)."""

    provider_name: str = "generic"

    def __init__(self, org_id: str = "org_default"):
        self.org_id = org_id

    @abstractmethod
    def is_configured(self) -> bool:
        """Return True when required env credentials are present."""

    @abstractmethod
    def push_audit_result(
        self,
        *,
        lead_id: str,
        call_id: str,
        audit_payload: dict[str, Any],
    ) -> dict[str, Any]:
        """Push audit score, summary, and compliance insights back to the CRM."""

    @abstractmethod
    def handle_webhook(self, payload: dict[str, Any], headers: dict[str, str] | None = None) -> dict[str, Any]:
        """Process inbound webhook (e.g. live call ended → queue audit)."""

    def _log_usage(
        self,
        *,
        endpoint: str,
        method: str = "POST",
        call_id: str | None = None,
        lead_id: str | None = None,
        user_id: str | None = None,
        status_code: int | None = None,
        success: bool = False,
        sync_attempt: int = 1,
        duration_ms: int | None = None,
        error_message: str | None = None,
    ) -> None:
        from database import log_crm_usage

        log_crm_usage(
            org_id=self.org_id,
            crm_provider=self.provider_name,
            endpoint=endpoint,
            method=method,
            call_id=call_id,
            lead_id=lead_id,
            user_id=user_id,
            status_code=status_code,
            success=success,
            sync_attempt=sync_attempt,
            duration_ms=duration_ms,
            error_message=error_message,
        )

    def _timed_request(self, fn, *, endpoint: str, call_id: str | None = None, lead_id: str | None = None):
        start = time.perf_counter()
        try:
            result = fn()
            ms = int((time.perf_counter() - start) * 1000)
            status = result.get("status_code") if isinstance(result, dict) else 200
            self._log_usage(
                endpoint=endpoint,
                call_id=call_id,
                lead_id=lead_id,
                status_code=status,
                success=bool(result.get("ok", True)) if isinstance(result, dict) else True,
                duration_ms=ms,
            )
            return result
        except Exception as exc:
            ms = int((time.perf_counter() - start) * 1000)
            self._log_usage(
                endpoint=endpoint,
                call_id=call_id,
                lead_id=lead_id,
                status_code=500,
                success=False,
                duration_ms=ms,
                error_message=str(exc)[:300],
            )
            raise
