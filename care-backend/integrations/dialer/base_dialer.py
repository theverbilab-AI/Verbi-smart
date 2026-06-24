"""Abstract dialer integration interface for VERBICARE."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class BaseDialer(ABC):
    """Base class for dialer providers (Exotel, Ozonetel, LeadSquared dialer, etc.)."""

    provider_name: str = "generic"

    def __init__(self, org_id: str = "org_default"):
        self.org_id = org_id

    @abstractmethod
    def is_configured(self) -> bool:
        pass

    @abstractmethod
    def fetch_recording(self, call_ref: str) -> dict[str, Any]:
        """Return { audio_url, call_id, agent_id, metadata } for a dialer call reference."""

    @abstractmethod
    def handle_call_completed_webhook(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Normalize dialer webhook payload for VERBICARE ingest."""
