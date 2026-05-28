#!/usr/bin/env python3
"""
Quick KPI regression checks (run from care-backend/):
  python scripts/test_scoring_kpis.py
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scoring_rules import detect_call_kpis, kpis_to_opening_audit  # noqa: E402


def run_case(name: str, transcript: str, **expect) -> None:
    kpis = detect_call_kpis(transcript)
    opening = kpis_to_opening_audit(kpis)
    ok = True
    for key, val in expect.items():
        actual = kpis.get(key, opening.get(key))
        if actual != val:
            ok = False
            print(f"  FAIL {key}: expected {val!r}, got {actual!r}")
    status = "PASS" if ok else "FAIL"
    print(f"{status} {name}")


def main() -> int:
    run_case(
        "Example 1 — Gaurav / Yes tell me",
        """Agent: Hello, hello, yes, this is Gaurav speaking.
Customer: Yes, tell me.""",
        rpc_confirmed=True,
        agent_intro=True,
    )

    run_case(
        "Example 2 — Am I speaking with Sagnik",
        """Agent: Am I speaking with Sagnik?
Customer: Yes speaking.""",
        rpc_confirmed=True,
    )

    run_case(
        "Example 3 — Third party safe",
        """Customer: He is my brother, he is not here.
Agent: Please ask him to call back.""",
        third_party=True,
        compliance_violation=False,
        critical_fail=0,
    )

    run_case(
        "Example 4 — Third party breach",
        """Customer: He is my brother.
Agent: His loan payment is overdue.""",
        third_party=True,
        compliance_violation=True,
        critical_fail=1,
    )

    ptp_kpis = detect_call_kpis(
        """Customer: I will do it in five to ten weeks.
Agent: Noted, thank you."""
    )
    assert ptp_kpis["ptp_detected"] == 1, "PTP weeks commitment"
    print("PASS Example 5 — PTP weeks")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
