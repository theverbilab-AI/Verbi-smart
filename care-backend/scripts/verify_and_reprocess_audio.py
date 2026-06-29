"""
Reprocess a call from archived audio and print proof metrics.
Usage: python scripts/verify_and_reprocess_audio.py CALL-D8013643
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv

load_dotenv()


def _metrics(call: dict) -> dict:
    analysis = call.get("analysis") or {}
    turns = analysis.get("speaker_turns") or []
    agents = sum(1 for t in turns if str(t.get("speaker", "")).lower() == "agent")
    customers = sum(1 for t in turns if str(t.get("speaker", "")).lower() == "customer")
    confs = [float(t["confidence"]) for t in turns if isinstance(t.get("confidence"), (int, float))]
    sources = {str(t.get("attribution_source") or "") for t in turns}
    return {
        "status": call.get("status"),
        "disposition": call.get("disposition"),
        "turn_count": len(turns),
        "agent_count": agents,
        "customer_count": customers,
        "min_conf": round(min(confs), 2) if confs else None,
        "avg_conf": round(sum(confs) / len(confs), 2) if confs else None,
        "attribution_sources": sorted(sources),
        "sample_customer_lines": [
            (t.get("text") or "")[:80]
            for t in turns[:20]
            if str(t.get("speaker", "")).lower() == "customer"
        ][:4],
    }


def main():
    call_id = sys.argv[1] if len(sys.argv) > 1 else "CALL-D8013643"
    from database import get_call, update_call
    from processor import reprocess_call_from_audio

    before = get_call(call_id) or {}
    print("=== BEFORE ===")
    print(_metrics(before))

    row = before
    ok = reprocess_call_from_audio(call_id, row, update_call)
    after = get_call(call_id) or {}
    print("\n=== AFTER (reprocess ok=%s) ===" % ok)
    m = _metrics(after)
    print(m)

    checks = {
        "47_turns": m["turn_count"] == 47,
        "agent_24": m["agent_count"] == 24,
        "customer_23": m["customer_count"] == 23,
        "conf_92": m["avg_conf"] is not None and m["avg_conf"] >= 0.9,
        "audio_diarization": m["attribution_sources"] == ["audio_diarization"],
        "disposition_app_issue": str(m["disposition"]).upper() == "APP_ISSUE",
        "processed": m["status"] == "processed",
    }
    print("\n=== PROOF CHECKS ===")
    for name, passed in checks.items():
        print(f"  {'PASS' if passed else 'FAIL'}: {name}")
    if not all(checks.values()):
        sys.exit(1)
    print("\nAll proof checks passed.")


if __name__ == "__main__":
    main()
