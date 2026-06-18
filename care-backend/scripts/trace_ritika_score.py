import sqlite3
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scoring_rules import (
    detect_call_context,
    detect_call_kpis,
    build_rules_fallback_result,
    _lines_by_speaker,
    _THIRD_PARTY_CUES,
)

conn = sqlite3.connect("care.db")
row = conn.execute(
    "SELECT transcript, filename FROM calls WHERE id='CALL-2F90045C'"
).fetchone()
transcript, fn = row
ctx = detect_call_context(transcript, fn)
print("filename:", fn)
print("ctx is_collections:", ctx["is_collections"])
kpis = detect_call_kpis(transcript, filename_hint=fn)
print("kpis is_collections:", kpis.get("is_collections"))
print("third_party:", kpis.get("third_party"), "violation:", kpis.get("compliance_violation"))
agent_lines, customer_lines = _lines_by_speaker(transcript)
ct = " ".join(customer_lines).lower()
for cue in _THIRD_PARTY_CUES:
    if cue in ct:
        print("customer cue hit:", repr(cue))
        for i, cl in enumerate(customer_lines):
            if cue in (cl or "").lower():
                print("  line", i, cl[:120])
rs = build_rules_fallback_result(transcript, fn)
print("score", rs["total_score"], rs["scores"])
print("flags", rs["compliance_flags"])
print("summary", (rs.get("summary") or "")[:250])
