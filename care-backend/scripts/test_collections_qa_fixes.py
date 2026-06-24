#!/usr/bin/env python3
"""Regression tests — speaker attribution, strict PTP, summary evidence, QA validation."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from processor import format_labelled_transcript, _classify_speaker_line
from scoring_rules import detect_call_kpis, _extract_ptp_details, detect_call_context, sanitize_transcript
from qa_validation import validate_collections_audit, build_evidence_summary


def assert_ptp(label: str, transcript: str, expect_ptp: bool):
    ctx = detect_call_context(transcript)
    ptp = _extract_ptp_details(transcript, ctx)
    ok = bool(ptp.get("ptp_detected")) == expect_ptp
    status = "PASS" if ok else "FAIL"
    print(f"  {status} {label}: ptp={ptp.get('ptp_detected')} reason={ptp.get('ptp_reason')!r}")
    return ok


def assert_speaker(label: str, text: str, expect: str):
    got = _classify_speaker_line(text)
    ok = got == expect
    print(f"  {'PASS' if ok else 'FAIL'} {label}: {got!r} (want {expect})")
    return ok


def main():
    ok = True

    print("\n=== Issue #2 — False PTP (death / try / agent date) ===")
    death_tx = sanitize_transcript("""Agent: Good afternoon sir.
Customer: My father passed away on the 24th.
Agent: I am sorry to hear that.""")
    ok &= assert_ptp("father death on 24th", death_tx, False)

    try_tx = sanitize_transcript("""Agent: You have to pay today sir.
Customer: Okay madam, I will try.
Agent: Don't try sir.""")
    ok &= assert_ptp("i will try not PTP", try_tx, False)

    agent_date_tx = sanitize_transcript("""Agent: So sir, from the 24th, right?
Customer: Yes.
Agent: You have to pay by then.""")
    ok &= assert_ptp("agent mentions 24th only", agent_date_tx, False)

    real_ptp_tx = sanitize_transcript("""Agent: When can you clear the payment?
Customer: I will pay on the 15th by UPI.""")
    ok &= assert_ptp("explicit pay on 15th", real_ptp_tx, True)

    print("\n=== Issue #1 — Speaker cues ===")
    ok &= assert_speaker("customer intro", "Hello, Krishna Jagadeesan speaking.", "Customer")
    ok &= assert_speaker("yes short", "Yes.", "Customer")
    ok &= assert_speaker("i will try", "Okay madam, I will try.", "Customer")
    ok &= assert_speaker("agent pay demand", "Sir, don't try, you have to pay today.", "Agent")
    ok &= assert_speaker("agent behalf", "I am speaking on behalf of Tala application.", "Agent")

    print("\n=== Issue #3 — Summary evidence ===")
    audit = {"ptp_detected": True, "ptp_date": "24th", "summary": "PTP secured by 24th", "disposition": "PTP"}
    summary = build_evidence_summary(death_tx, audit)
    ok &= "PTP secured" not in summary and "No PTP" in summary
    print(f"  {'PASS' if 'No PTP' in summary else 'FAIL'} death call summary: {summary[:100]}...")

    print("\n=== Issue #4 — QA validation ===")
    qa = validate_collections_audit(death_tx, audit)
    ok &= qa.get("review_required") and qa.get("corrections", {}).get("disposition") == "NO_PTP"
    print(f"  {'PASS' if qa.get('review_required') else 'FAIL'} review_required status={qa.get('qa_status')}")

    print("\n" + ("ALL PASSED" if ok else "SOME TESTS FAILED"))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
