#!/usr/bin/env python3
"""Final Collections QA audit — duplicate upload + opening audit consistency."""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scoring_rules import detect_call_kpis, kpis_to_opening_audit, resolve_disposition, sanitize_transcript
from qa_validation import validate_collections_audit, build_evidence_summary

GAURI_TX = sanitize_transcript("""Customer: Hello, Krishna Jagadeesan speaking.
Customer: Yes.
Agent: I am speaking on behalf of the Tala App system.
Agent: The call is being recorded.""")


def audit_duplicate_consistency() -> bool:
    """Same transcript must yield identical opening audit + disposition."""
    results = []
    for _ in range(2):
        kpis = detect_call_kpis(GAURI_TX)
        opening = kpis_to_opening_audit(kpis)
        disp = resolve_disposition(GAURI_TX, kpis)
        results.append((opening, disp, kpis.get("customer_name_confirmed"), kpis.get("ptp_detected")))

    ok = results[0] == results[1]
    print(f"{'PASS' if ok else 'FAIL'} duplicate transcript -> identical KPIs (2 simulated uploads)")
    if not ok:
        print(f"  run1: {results[0]}")
        print(f"  run2: {results[1]}")
    return ok


def audit_enrich_simulation() -> bool:
    """Simulate stale DB vs enrich-on-read correction."""
    stale = {
        "ptp_detected": True,
        "disposition": "PTP",
        "summary": "PTP secured by customer.",
        "confidence": 90,
        "analysis": {"opening_audit": {"customer_name_used": False}},
    }
    kpis = detect_call_kpis(GAURI_TX)
    opening = kpis_to_opening_audit(kpis)
    audit_stub = {**stale, "opening_audit": stale["analysis"]["opening_audit"]}
    qa = validate_collections_audit(GAURI_TX, audit_stub, speaker_turns=[])
    corrected = dict(stale)
    for k, v in (qa.get("corrections") or {}).items():
        corrected[k] = v
    corrected_opening = opening

    ok = (
        corrected.get("ptp_detected") is False
        and corrected.get("disposition") in ("NO_PTP", "OTHER")
        and corrected_opening.get("customer_name_used") is True
        and qa.get("review_required") is True
    )
    print(f"{'PASS' if ok else 'FAIL'} enrich corrects stale PTP + restores customer name")
    if not ok:
        print(f"  ptp={corrected.get('ptp_detected')} disp={corrected.get('disposition')}")
        print(f"  name={corrected_opening.get('customer_name_used')} review={qa.get('review_required')}")
    return ok


def audit_review_required() -> bool:
    cases = [
        ("false PTP claim", {"ptp_detected": True, "disposition": "PTP", "confidence": 85}, True),
        ("clean no-ptp", {"ptp_detected": False, "disposition": "NO_PTP", "confidence": 80}, False),
    ]
    ok = True
    for label, audit, expect_review in cases:
        qa = validate_collections_audit(GAURI_TX, audit)
        got = bool(qa.get("review_required"))
        if got != expect_review:
            ok = False
            print(f"  FAIL review_required {label}: got {got}, want {expect_review}")
        else:
            print(f"  PASS review_required {label}: {got}")
    print(f"{'PASS' if ok else 'FAIL'} review_required logic")
    return ok


def main() -> int:
    print("\n=== Final Collections QA Audit ===\n")
    ok = True
    ok &= audit_duplicate_consistency()
    ok &= audit_enrich_simulation()
    ok &= audit_review_required()
    summary = build_evidence_summary(GAURI_TX, {"disposition": "NO_PTP"})
    ok &= "PTP secured" not in summary and "Krishna" in summary
    print(f"{'PASS' if 'PTP secured' not in summary else 'FAIL'} summary grounded (no false PTP)")
    print("\n" + ("AUDIT PASSED" if ok else "AUDIT FAILED"))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
