"""Configurable audit modes for VERBICARE (collections vs sales)."""

from __future__ import annotations

import os

from audit_modes.collections import COLLECTIONS, get_collections_prompt
from audit_modes.sales import SALES, SALES_SCORING_PROMPT

AUDIT_MODES = frozenset({COLLECTIONS, SALES})
DEFAULT_AUDIT_MODE = COLLECTIONS


def normalize_audit_mode(mode: str | None) -> str:
    m = (mode or os.getenv("CARE_DEFAULT_AUDIT_MODE") or DEFAULT_AUDIT_MODE).strip().lower()
    return m if m in AUDIT_MODES else DEFAULT_AUDIT_MODE


def get_scoring_prompt(mode: str | None = None) -> str:
    m = normalize_audit_mode(mode)
    if m == SALES:
        return SALES_SCORING_PROMPT
    return get_collections_prompt()


def max_score_for_mode(mode: str | None = None) -> int:
    return 10 if normalize_audit_mode(mode) == SALES else 20
