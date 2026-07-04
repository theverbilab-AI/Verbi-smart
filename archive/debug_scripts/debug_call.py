"""Debug scoring for a call or audio file."""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv

load_dotenv()

from database import init_db, get_call
from scoring_rules import (
    build_rules_fallback_result,
    detect_call_kpis,
    score_a1_opening,
    detect_call_context,
    audit_opening_elements,
)


def main():
    init_db()
    call_id = sys.argv[1] if len(sys.argv) > 1 else "CALL-8F187120"
    call = get_call(call_id)
    if not call:
        print("Call not found:", call_id)
        sys.exit(1)
    t = call.get("transcript") or ""
    fn = call.get("filename") or ""
    print("call_id:", call_id, "file:", fn, "score:", call.get("score"))
    print("breakdown:", call.get("scores_breakdown"))
    a = call.get("analysis") or {}
    if isinstance(a, str):
        a = json.loads(a)
    print("opening_audit:", a.get("opening_audit"))
    print("\n--- transcript first 1200 chars ---\n", t[:1200])
    kpis = detect_call_kpis(t, filename_hint=fn)
    print("\n--- KPIs ---")
    for k in ("rpc_confirmed", "agent_intro", "customer_name_confirmed", "disclaimer_given", "ptp_detected"):
        print(f"  {k}: {kpis.get(k)}")
    ctx = detect_call_context(t, fn)
    ctx["rpc_confirmed"] = kpis["rpc_confirmed"]
    print("A1 rules score:", score_a1_opening(t, ctx))
    rs = build_rules_fallback_result(t, fn)
    print("rules total:", rs.get("total_score"), rs.get("scores"))


if __name__ == "__main__":
    main()
