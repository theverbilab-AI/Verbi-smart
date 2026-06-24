"""
Collections QA validation — evidence checks before final audit output.
"""
from __future__ import annotations

import re
from typing import Any

from scoring_rules import (
    _extract_ptp_details,
    _has_explicit_payment_commitment,
    _lines_by_speaker,
    detect_call_context,
    detect_call_kpis,
    sanitize_transcript,
    summarize_transcript_fallback,
)

QA_REVIEW_THRESHOLD = 65


def _speaker_balance(transcript: str) -> dict[str, Any]:
    agent_n = customer_n = 0
    for raw in (transcript or "").splitlines():
        m = re.match(r"^(agent|customer)\s*:", raw.strip(), re.I)
        if not m:
            continue
        if m.group(1).lower() == "agent":
            agent_n += 1
        else:
            customer_n += 1
    total = agent_n + customer_n
    ratio = agent_n / total if total else 1.0
    return {
        "agent_lines": agent_n,
        "customer_lines": customer_n,
        "agent_ratio": round(ratio, 3),
        "imbalanced": total >= 4 and (ratio > 0.92 or ratio < 0.08),
    }


def extract_verified_facts(transcript: str, audit: dict[str, Any] | None = None) -> dict[str, Any]:
    """Facts allowed in summary — each must be grounded in transcript."""
    text = sanitize_transcript(transcript or "")
    audit = audit or {}
    ctx = detect_call_context(text)
    kpis = detect_call_kpis(text)
    ptp = _extract_ptp_details(text, ctx)

    facts: dict[str, Any] = {
        "rpc_confirmed": bool(kpis.get("rpc_confirmed")),
        "ptp_detected": bool(ptp.get("ptp_detected")),
        "ptp_date": ptp.get("ptp_date") or "",
        "ptp_amount": ptp.get("ptp_amount") or "",
        "ptp_mode": ptp.get("ptp_mode") or "",
        "ptp_confidence": int(ptp.get("ptp_confidence") or 0),
        "ptp_reason": ptp.get("ptp_reason") or "",
        "disposition": audit.get("disposition") or kpis.get("dispositions", ["OTHER"])[0],
        "third_party": bool(kpis.get("third_party")),
    }

    opening = (audit.get("opening_audit") or audit.get("analysis", {}).get("opening_audit") or {})
    facts["disclaimer_given"] = bool(opening.get("disclaimer_given"))

    agent_lines, customer_lines = _lines_by_speaker(text)
    facts["customer_snippet"] = " ".join(customer_lines[:2])[:240]
    facts["agent_snippet"] = " ".join(agent_lines[:2])[:240]
    return facts


def build_evidence_summary(transcript: str, audit: dict[str, Any] | None = None) -> str:
    """Summary text built only from verified facts."""
    facts = extract_verified_facts(transcript, audit)
    parts: list[str] = []

    if facts.get("disclaimer_given"):
        parts.append("Recording disclaimer was given.")
    if facts.get("rpc_confirmed"):
        parts.append("Right party contact (RPC) confirmed.")

    if facts.get("ptp_detected"):
        bit = "Customer committed to pay"
        if facts.get("ptp_date"):
            bit += f" by {facts['ptp_date']}"
        if facts.get("ptp_amount"):
            bit += f" (₹{facts['ptp_amount']})"
        parts.append(bit + ".")
    elif facts.get("ptp_reason"):
        parts.append(f"No PTP: {facts['ptp_reason']}")

    disp = str(facts.get("disposition") or "OTHER").replace("_", " ")
    if facts.get("ptp_detected"):
        disp = "PTP"
    elif not facts.get("ptp_detected"):
        disp = "NO PTP"
    if disp and disp.upper() not in {"OTHER", "NONE"}:
        parts.append(f"Disposition: {disp}.")

    snippet = facts.get("customer_snippet") or facts.get("agent_snippet")
    if snippet:
        parts.append(snippet + ("…" if len(snippet) >= 240 else ""))

    return " ".join(parts) if parts else summarize_transcript_fallback(transcript, audit)


def validate_collections_audit(
    transcript: str,
    audit: dict[str, Any],
    speaker_log: list[dict] | None = None,
) -> dict[str, Any]:
    """
    Final QA gate. May downgrade PTP/disposition and flag REVIEW_REQUIRED.
    """
    text = sanitize_transcript(transcript or "")
    ctx = detect_call_context(text)
    kpis = detect_call_kpis(text)
    ptp = _extract_ptp_details(text, ctx)
    balance = _speaker_balance(text)
    speaker_log = speaker_log or []

    notes: list[str] = []
    confidence = int(audit.get("confidence") or kpis.get("confidence") or 70)
    corrections: dict[str, Any] = {}

    if balance["imbalanced"]:
        confidence -= 20
        notes.append(
            f"Speaker imbalance: {balance['agent_lines']} agent / {balance['customer_lines']} customer lines."
        )

    claimed_ptp = bool(audit.get("ptp_detected"))
    verified_ptp = bool(ptp.get("ptp_detected"))

    if claimed_ptp and not verified_ptp:
        confidence -= 25
        notes.append(ptp.get("ptp_reason") or "PTP not supported by transcript evidence.")
        corrections["ptp_detected"] = False
        corrections["ptp_date"] = None
        corrections["ptp_amount"] = None
        corrections["ptp_mode"] = None
        corrections["disposition"] = "NO_PTP"
        flags = [f for f in (audit.get("compliance_flags") or []) if str(f).upper() != "PTP_DETECTED"]
        if "NO_PTP" not in [str(f).upper() for f in flags]:
            flags.append("NO_PTP")
        corrections["compliance_flags"] = flags
        det = [d for d in (audit.get("ai_detection") or []) if "PTP_DETECTED" not in str(d).upper()]
        if "NO_PTP" not in [str(d).upper() for d in det]:
            det.append("NO_PTP")
        corrections["ai_detection"] = det or ["NONE"]

    summary = str(audit.get("summary") or "")
    if "ptp secured" in summary.lower() and not verified_ptp:
        corrections["summary"] = build_evidence_summary(text, audit)
        notes.append("Summary corrected — removed unverified PTP claim.")

    if speaker_log:
        notes.append(f"Speaker corrections applied: {len(speaker_log)} line(s).")

    review_required = confidence < QA_REVIEW_THRESHOLD or balance["imbalanced"] or (
        claimed_ptp and not verified_ptp
    )

    return {
        "qa_confidence": max(0, min(100, confidence)),
        "review_required": review_required,
        "qa_status": "REVIEW_REQUIRED" if review_required else "AUTO_APPROVED",
        "validation_notes": notes,
        "corrections": corrections,
        "verified_facts": extract_verified_facts(text, audit),
        "speaker_balance": balance,
    }
