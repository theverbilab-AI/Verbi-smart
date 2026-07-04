import sqlite3
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scoring_rules import (
    cleanup_transcript_for_scoring,
    detect_call_kpis,
    apply_non_collections_guardrail,
    score_all_parameters,
    apply_sequential_parameter_gating,
)

conn = sqlite3.connect("care.db")
t, fn = conn.execute(
    "SELECT transcript, filename FROM calls WHERE id='CALL-2F90045C'"
).fetchone()
clean = cleanup_transcript_for_scoring(t)
kpis = detect_call_kpis(clean, filename_hint=fn)
ctx = kpis["_ctx"]
ctx["rpc_confirmed"] = kpis["rpc_confirmed"]
print("guard check", ctx.get("is_collections"), ctx.get("is_wrong_number"))
scores = apply_sequential_parameter_gating(score_all_parameters(clean, ctx), ctx)
print("scores before guardrail", scores, "sum", sum(scores.values()))
r = {"scores": scores, "compliance_flags": list(kpis.get("compliance_flags") or [])}
o = apply_non_collections_guardrail(r, ctx)
print("after guardrail", o["scores"], "sum", o.get("total_score"), o.get("compliance_flags"))
