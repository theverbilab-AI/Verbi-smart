#!/usr/bin/env python3
"""
Export CARE calls for manual QA audit vs product scores (Excel-friendly CSV).

Usage:
  cd care-backend
  python scripts/audit_comparison_export.py
  python scripts/audit_comparison_export.py --limit 50 --output exports/audit_comparison.csv
  python scripts/audit_comparison_export.py --rescore   # add latest-rules columns

Columns include product scores + blank manual_* columns for Rakesh's 2pm review.
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database import list_calls, init_db  # noqa: E402
from scoring_rules import build_rules_fallback_result  # noqa: E402


def _as_list(val) -> list:
    if val is None:
        return []
    if isinstance(val, list):
        return val
    if isinstance(val, str):
        try:
            parsed = json.loads(val)
            return parsed if isinstance(parsed, list) else [val]
        except Exception:
            return [x.strip() for x in val.split(";") if x.strip()]
    return [str(val)]


def _opening(call: dict) -> dict:
    analysis = call.get("analysis") or {}
    if isinstance(analysis, str):
        try:
            analysis = json.loads(analysis)
        except Exception:
            analysis = {}
    return analysis.get("opening_audit") or call.get("opening_audit") or {}


def _scores(call: dict) -> dict:
    bd = call.get("scores_breakdown") or {}
    if bd:
        return bd
    analysis = call.get("analysis") or {}
    if isinstance(analysis, str):
        try:
            analysis = json.loads(analysis)
        except Exception:
            analysis = {}
    return analysis.get("scores") or {}


def _rescore_row(transcript: str, filename: str) -> dict:
    if not (transcript or "").strip():
        return {}
    try:
        return build_rules_fallback_result(transcript, filename_hint=filename or "")
    except Exception as exc:
        return {"_error": str(exc)}


def main():
    parser = argparse.ArgumentParser(description="CARE audit comparison CSV export")
    parser.add_argument("--limit", type=int, default=500, help="Max calls to export")
    parser.add_argument("--org", default="org_default", help="Organisation id")
    parser.add_argument("--output", default="", help="Output path (.csv)")
    parser.add_argument("--rescore", action="store_true", help="Add latest-rules rescore columns")
    args = parser.parse_args()

    init_db()
    calls = list_calls(org_id=args.org, status="processed", limit=args.limit)
    calls = sorted(calls, key=lambda c: c.get("uploaded_at") or "", reverse=True)

    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M")
    out = args.output or os.path.join(
        os.path.dirname(os.path.dirname(__file__)),
        "exports",
        f"CARE_Audit_Comparison_{stamp}.csv",
    )
    os.makedirs(os.path.dirname(out), exist_ok=True)

    headers = [
        "call_id", "filename", "agent_id", "loan_id", "uploaded_at", "processed_at",
        "product_score", "product_score_pct", "product_grade", "product_disposition",
        "product_risk_level", "product_ptp_detected", "product_ptp_date", "product_ptp_amount",
        "rpc_confirmed", "disclaimer_given", "agent_intro_done", "customer_name_used",
        "product_A1_opening", "product_A2_case_knowledge", "product_A3_probing",
        "product_A4_negotiation", "product_A5_commitment_ptp", "product_A6_closing",
        "product_A7_professionalism", "product_A8_call_handling", "product_A9_troubleshooting",
        "product_ai_detection", "product_key_issues", "product_compliance_flags",
        "transcript_preview",
        "manual_score", "manual_grade", "manual_rpc", "manual_ptp", "manual_disposition",
        "manual_A1", "manual_A2", "manual_A3", "manual_A4", "manual_A5",
        "manual_A6", "manual_A7", "manual_A8", "manual_A9",
        "score_delta", "match_yes_no", "auditor_notes",
    ]
    if args.rescore:
        headers.extend([
            "rules_rescore_total", "rules_rescore_grade", "rules_rescore_ptp",
            "rules_rescore_rpc", "rules_rescore_disposition", "rules_delta_vs_product",
        ])

    with open(out, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=headers, extrasaction="ignore")
        writer.writeheader()
        for c in calls:
            opening = _opening(c)
            scores = _scores(c)
            transcript = (c.get("transcript") or "")[:500]
            row = {
                "call_id": c.get("id", ""),
                "filename": c.get("filename", ""),
                "agent_id": c.get("agent_id", ""),
                "loan_id": c.get("loan_id", ""),
                "uploaded_at": c.get("uploaded_at", ""),
                "processed_at": c.get("processed_at", ""),
                "product_score": c.get("score", ""),
                "product_score_pct": c.get("score_pct", ""),
                "product_grade": c.get("grade", ""),
                "product_disposition": c.get("disposition", ""),
                "product_risk_level": c.get("risk_level", ""),
                "product_ptp_detected": c.get("ptp_detected", ""),
                "product_ptp_date": c.get("ptp_date", ""),
                "product_ptp_amount": c.get("ptp_amount", ""),
                "rpc_confirmed": opening.get("rpc_confirmed", ""),
                "disclaimer_given": opening.get("disclaimer_given", ""),
                "agent_intro_done": opening.get("agent_intro_done", ""),
                "customer_name_used": opening.get("customer_name_used", ""),
                "product_A1_opening": scores.get("A1_opening", ""),
                "product_A2_case_knowledge": scores.get("A2_case_knowledge", ""),
                "product_A3_probing": scores.get("A3_probing", ""),
                "product_A4_negotiation": scores.get("A4_negotiation", ""),
                "product_A5_commitment_ptp": scores.get("A5_commitment_ptp", ""),
                "product_A6_closing": scores.get("A6_closing", ""),
                "product_A7_professionalism": scores.get("A7_professionalism", ""),
                "product_A8_call_handling": scores.get("A8_call_handling", ""),
                "product_A9_troubleshooting": scores.get("A9_troubleshooting", ""),
                "product_ai_detection": "; ".join(_as_list(c.get("ai_detection"))),
                "product_key_issues": "; ".join(_as_list(c.get("key_issues"))),
                "product_compliance_flags": "; ".join(_as_list(c.get("compliance_flags"))),
                "transcript_preview": transcript.replace("\n", " | "),
            }
            if args.rescore:
                rs = _rescore_row(c.get("transcript") or "", c.get("filename") or "")
                prod = int(c.get("score") or 0)
                new_total = int(rs.get("total_score") or 0)
                row["rules_rescore_total"] = new_total
                row["rules_rescore_grade"] = rs.get("grade", "")
                row["rules_rescore_ptp"] = rs.get("ptp_detected", "")
                oa = rs.get("opening_audit") or {}
                row["rules_rescore_rpc"] = oa.get("rpc_confirmed", "")
                row["rules_rescore_disposition"] = rs.get("disposition", "")
                row["rules_delta_vs_product"] = new_total - prod
            writer.writerow(row)

    print(f"Exported {len(calls)} calls -> {out}")
    print("Fill manual_* columns in Excel for the 2pm audit.")


if __name__ == "__main__":
    main()
