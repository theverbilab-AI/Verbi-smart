"""CRM provider registry — add new CRMs here without changing core audit pipeline."""

from __future__ import annotations

from integrations.crm.base_crm import BaseCRM


def get_crm(provider: str = "leadsquared", org_id: str = "org_default") -> BaseCRM:
    p = (provider or "leadsquared").strip().lower()
    if p == "leadsquared":
        from integrations.crm.leadsquared import LeadSquaredCRM
        return LeadSquaredCRM(org_id=org_id)
    raise ValueError(f"Unsupported CRM provider: {provider}")
