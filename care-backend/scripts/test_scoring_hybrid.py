#!/usr/bin/env python3
"""Hybrid scoring regression — Hindi/Marathi/English RPC, PTP, third-party, score floor."""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scoring_rules import (  # noqa: E402
    aggregate_top_customer_issues,
    apply_kpi_overrides,
    apply_minimum_score_guard,
    cleanup_transcript_for_scoring,
    detect_call_kpis,
    detect_customer_issues,
    run_hybrid_scoring,
)


def assert_kpis(name: str, transcript: str, **expect) -> bool:
    kpis = apply_kpi_overrides(transcript, detect_call_kpis(transcript))
    ok = True
    for key, val in expect.items():
        actual = kpis.get(key)
        if actual != val:
            ok = False
            print(f"  FAIL {key}: expected {val!r}, got {actual!r}")
    print(f"{'PASS' if ok else 'FAIL'} {name}")
    return ok


def assert_ptp(name: str, transcript: str, detected: bool, date_fragment: str = "") -> bool:
    kpis = detect_call_kpis(transcript)
    ok = bool(kpis.get("ptp_detected")) == detected
    if detected and date_fragment:
        ok = ok and date_fragment.lower() in str(kpis.get("ptp_date") or "").lower()
    if not ok:
        print(
            f"  FAIL ptp_detected={kpis.get('ptp_detected')} "
            f"ptp_date={kpis.get('ptp_date')!r} (want detected={detected})"
        )
    print(f"{'PASS' if ok else 'FAIL'} {name}")
    return ok


def assert_score_floor(name: str, transcript: str) -> bool:
    llm_zero = {
        "scores": {k: 0 for k in (
            "A1_opening", "A2_case_knowledge", "A3_probing", "A4_negotiation",
            "A5_commitment_ptp", "A6_closing", "A7_professionalism",
            "A8_call_handling", "A9_troubleshooting",
        )},
        "compliance_flags": [],
        "ai_detection": ["NONE"],
    }
    out = run_hybrid_scoring(llm_zero, transcript)
    total = int(out.get("total_score") or 0)
    ok = total >= 4
    if not ok:
        print(f"  FAIL total_score={total}, expected floor >= 4")
    print(f"{'PASS' if ok else 'FAIL'} {name}")
    return ok


def test_cleanup_preserves_labels() -> bool:
    raw = "Agent:  Haan   ji\nCustomer: Yes tell me"
    cleaned = cleanup_transcript_for_scoring(raw)
    ok = "Agent: Haan ji" in cleaned and "Customer: Yes tell me" in cleaned
    print(f"{'PASS' if ok else 'FAIL'} cleanup preserves Agent/Customer lines")
    return ok


def main() -> int:
    failed = 0

    if not test_cleanup_preserves_labels():
        failed += 1

    rpc_cases = [
        ("RPC EN — yes tell me", """Agent: Good morning, this is Rahul calling from Tala.
Customer: Yes, tell me.""", {"rpc_confirmed": True}),
        ("RPC EN — yes speaking", """Agent: Am I speaking with Mr Sharma?
Customer: Yes speaking.""", {"rpc_confirmed": True}),
        ("RPC HI — haan ji boliye", """Agent: Namaste, main Tala se bol raha hoon.
Customer: Haan ji, boliye.""", {"rpc_confirmed": True}),
        ("RPC HI — main bol raha hu", """Agent: Sir, aap ka naam confirm karna hai.
Customer: Haan, main bol raha hu.""", {"rpc_confirmed": True}),
        ("RPC HI — main bol rahi hu", """Agent: Kya main Mrs Patel se baat kar rahi hoon?
Customer: Ji, main bol rahi hu.""", {"rpc_confirmed": True}),
        ("RPC MR — ho", """Agent: Mi Tala madhun bolto aahe.
Customer: Ho, bolta.""", {"rpc_confirmed": True}),
        ("RPC FALSE — wrong number", """Agent: Am I speaking with Ravi?
Customer: Galat number hai, wrong number.""", {"rpc_confirmed": False}),
        ("RPC FALSE — wo nahi hai", """Agent: Kya main Suresh se baat kar sakta hoon?
Customer: Wo nahi hai, bahar gaya hai.""", {"rpc_confirmed": False}),
        ("RPC FALSE — call later", """Agent: Payment ke baare mein baat karni hai.
Customer: Abhi busy hoon, call later.""", {"rpc_confirmed": False}),
        ("RPC FALSE — who are you", """Customer: Who are you? Kaun bol rahe ho?""", {"rpc_confirmed": False}),
    ]
    for name, tx, expect in rpc_cases:
        if not assert_kpis(name, tx, **expect):
            failed += 1

    ptp_cases = [
        ("PTP HI — kal karunga", """Customer: Kal karunga payment.""", True, "tomorrow"),
        ("PTP HI — raat mein karunga", """Customer: Raat mein karunga.""", True, "tonight"),
        ("PTP HI — parso karunga", """Customer: Parso karunga.""", True, "day after"),
        ("PTP EN — tomorrow", """Customer: I will pay tomorrow by UPI.""", True, "tomorrow"),
        ("PTP EN — next week", """Customer: I can pay next week after salary.""", True, "next week"),
        ("PTP HI — arrange karunga", """Customer: Salary ke baad arrange karunga.""", True, "after salary"),
        ("PTP none", """Customer: Nahi dunga, refuse.""", False, ""),
    ]
    for name, tx, det, frag in ptp_cases:
        if not assert_ptp(name, tx, det, frag):
            failed += 1

    third_cases = [
        (
            "Third party SAFE — no loan disclosure",
            """Customer: Main unki behen bol rahi hoon, wo ghar pe nahi hai.
Agent: Theek hai, jab aayenge tab callback kar lena.""",
            {"third_party": True, "compliance_violation": False, "critical_fail": 0},
        ),
        (
            "Third party BREACH — loan disclosed",
            """Customer: Mummy bol rahi hoon, wo bahar gaya hai.
Agent: Unka loan outstanding 15000 hai, EMI pending hai.""",
            {"third_party": True, "compliance_violation": True, "critical_fail": 1},
        ),
    ]
    for name, tx, expect in third_cases:
        if not assert_kpis(name, tx, **expect):
            failed += 1

    if not assert_score_floor(
        "Score floor — collections call with RPC",
        """Agent: Good morning, this is Amit from Tala collections.
Customer: Haan ji, boliye.
Agent: Your EMI is pending, can you pay tomorrow?
Customer: Kal kar dunga.""",
    ):
        failed += 1

    issues = detect_customer_issues(
        """Agent: Why is payment pending?
Customer: Mera job chala gaya, paisa nahi hai abhi."""
    )
    if "FINANCIAL_HARDSHIP" not in issues:
        print(f"  FAIL customer issues: {issues}")
        failed += 1
    else:
        print("PASS customer issue — financial hardship")

    top = aggregate_top_customer_issues([
        {"status": "processed", "analysis": {"customer_issues": ["FINANCIAL_HARDSHIP"]}},
        {"status": "processed", "analysis": {"customer_issues": ["FINANCIAL_HARDSHIP", "APP_PAYMENT_ISSUE"]}},
        {"status": "processed", "dispositions": ["APP_ISSUE"]},
    ], limit=3)
    top_keys = {row["issue"]: row["count"] for row in top}
    ok_top = top_keys.get("FINANCIAL_HARDSHIP") == 2 and top_keys.get("APP_PAYMENT_ISSUE") == 2
    if not ok_top:
        print(f"  FAIL top issues: {top}")
        failed += 1
    else:
        print("PASS top 3 customer issues aggregation")

    print("\nDone." if not failed else f"\n{failed} case(s) failed.")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
