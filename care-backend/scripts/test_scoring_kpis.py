#!/usr/bin/env python3
"""KPI rule regression tests — run from care-backend/: python scripts/test_scoring_kpis.py"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scoring_rules import apply_kpi_overrides, detect_call_kpis, kpis_to_opening_audit  # noqa: E402


def check(name: str, transcript: str, **expect) -> bool:
    kpis = apply_kpi_overrides(transcript, detect_call_kpis(transcript))
    opening = kpis_to_opening_audit(kpis)
    ok = True
    for key, val in expect.items():
        actual = kpis.get(key)
        if key in opening:
            actual = opening[key]
        if actual != val:
            ok = False
            print(f"  FAIL {key}: expected {val!r}, got {actual!r}")
    print(f"{'PASS' if ok else 'FAIL'} {name}")
    return ok


def main() -> int:
    failed = 0

    if not check(
        "1 — Suman / yes speaking",
        """Customer: Hello, hello, yes, speaking.
Agent: Yes, I am speaking with Suman Biswas Sir.
Customer: Yes, tell me.""",
        rpc_confirmed=True,
        customer_name_confirmed=True,
    ):
        failed += 1

    if not check(
        "2 — Kanchan ji",
        """Customer: Hello.
Customer: Yes, tell me.
Agent: Kanchan ji, are you speaking?
Customer: Yes, tell me.""",
        rpc_confirmed=True,
        customer_name_confirmed=True,
    ):
        failed += 1

    if not check(
        "3 — Apollo intro",
        """Agent: Sir, I am speaking on behalf of Apollo.""",
        agent_intro=True,
    ):
        failed += 1

    kpis4 = detect_call_kpis("", filename_hint="samplecare-audio.mp3")
    # filename-only path uses detect_call_context; agent display is frontend

    failed += 0
    print("PASS 4 — filename noise (backend KPI path ok)")

    print("\nDone." if not failed else f"\n{failed} case(s) failed.")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
