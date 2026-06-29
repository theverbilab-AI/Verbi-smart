"""
Client-facing KPI labels/scores for exports (dashboard uses VITE_* mirror).

Internal DB keys unchanged — only presentation layer.
"""
from __future__ import annotations

import os
import re

_NATIVE_MAX = {
    "A1_opening": 2,
    "A2_case_knowledge": 2,
    "A3_probing": 3,
    "A4_negotiation": 3,
    "A5_commitment_ptp": 3,
    "A6_closing": 2,
    "A7_professionalism": 3,
    "A8_call_handling": 1,
    "A9_troubleshooting": 1,
}

_COLLECTIONS_KEYS = list(_NATIVE_MAX.keys())
COLLECTIONS_KPI_KEYS = _COLLECTIONS_KEYS


def kpi_display_max() -> int:
    try:
        return max(1, int(os.getenv("CARE_KPI_DISPLAY_MAX", "3")))
    except ValueError:
        return 3


def kpi_mask_names() -> bool:
    return os.getenv("CARE_KPI_MASK_NAMES", "").strip().lower() in ("1", "true", "yes")


def collections_kpi_client_label(index: int, native_key: str) -> str:
    if kpi_mask_names():
        return f"P{index + 1}"
    return native_key.replace("_", " ").title()


def scale_kpi_score(raw: int | float | None, native_max: int) -> tuple[int, int]:
    """Return (display_score, display_max) for client exports."""
    try:
        val = int(raw or 0)
    except (TypeError, ValueError):
        val = 0
    display_max = kpi_display_max()
    if display_max == native_max or native_max <= 0:
        return val, native_max
    scaled = round((val / native_max) * display_max)
    return max(0, min(display_max, scaled)), display_max


def collections_csv_headers() -> list[str]:
    if kpi_mask_names():
        return [f"P{i + 1}" for i in range(len(_COLLECTIONS_KEYS))]
    return [
        "A1 Opening",
        "A2 Case Knowledge",
        "A3 Probing",
        "A4 Negotiation",
        "A5 Commitment",
        "A6 Closing",
        "A7 Professionalism",
        "A8 Call Handling",
        "A9 Troubleshooting",
    ]
