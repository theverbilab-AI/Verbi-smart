"""Role and permission helpers for VERBICARE RBAC."""

from __future__ import annotations

import json
from typing import Any

ALL_PERMISSIONS: list[str] = [
    "dashboard_view",
    "upload_calls",
    "view_reports",
    "export_reports",
    "manage_users",
    "manage_settings",
    "view_call_details",
    "delete_calls",
    "compliance_flags",
    "agent_performance",
    "crm_usage",
]

ADMIN_ROLES = frozenset({"super_admin", "admin"})

ROLE_DEFAULTS: dict[str, list[str]] = {
    "super_admin": list(ALL_PERMISSIONS),
    "admin": list(ALL_PERMISSIONS),
    "qa_manager": [
        "dashboard_view",
        "upload_calls",
        "view_reports",
        "export_reports",
        "view_call_details",
        "compliance_flags",
        "agent_performance",
    ],
    "team_leader": [
        "dashboard_view",
        "view_reports",
        "view_call_details",
        "compliance_flags",
        "agent_performance",
    ],
    "read_only": [
        "dashboard_view",
        "view_reports",
        "view_call_details",
    ],
    "user": [
        "dashboard_view",
        "view_call_details",
    ],
}


def _parse_permissions_json(raw: Any) -> list[str] | None:
    if raw is None or raw == "":
        return None
    if isinstance(raw, list):
        return [p for p in raw if p in ALL_PERMISSIONS]
    if isinstance(raw, str):
        try:
            data = json.loads(raw)
            if isinstance(data, list):
                return [p for p in data if p in ALL_PERMISSIONS]
        except Exception:
            return None
    return None


def resolve_user_permissions(user: dict | None) -> set[str]:
    if not user:
        return set()
    role = (user.get("role") or "user").strip()
    if role in ADMIN_ROLES:
        return set(ALL_PERMISSIONS)
    custom = _parse_permissions_json(user.get("permissions"))
    if custom is not None and len(custom) > 0:
        return set(custom)
    return set(ROLE_DEFAULTS.get(role, ROLE_DEFAULTS["user"]))


def user_has_permission(user: dict | None, permission: str) -> bool:
    if not user:
        return False
    return permission in resolve_user_permissions(user)


def permissions_list(user: dict | None) -> list[str]:
    return sorted(resolve_user_permissions(user))


def sanitize_permissions_payload(raw: Any) -> list[str]:
    parsed = _parse_permissions_json(raw)
    if not parsed and isinstance(raw, list):
        alias = {"view_dashboard": "dashboard_view"}
        parsed = [alias.get(p, p) for p in raw if alias.get(p, p) in ALL_PERMISSIONS or p in ALL_PERMISSIONS]
        parsed = [p for p in parsed if p in ALL_PERMISSIONS]
    if not parsed:
        return []
    return parsed


VALID_ROLES = frozenset({"super_admin", "admin", "qa_manager", "team_leader", "read_only", "user"})


def validate_role(role: str) -> str | None:
    r = (role or "").strip()
    return r if r in VALID_ROLES else None
