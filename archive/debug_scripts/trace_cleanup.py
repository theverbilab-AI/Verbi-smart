import sqlite3
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scoring_rules import (
    cleanup_transcript_for_scoring,
    detect_call_context,
    detect_call_kpis,
    apply_phase1_scoring,
)

conn = sqlite3.connect("care.db")
row = conn.execute(
    "SELECT transcript, filename FROM calls WHERE id='CALL-2F90045C'"
).fetchone()
transcript, fn = row
clean = cleanup_transcript_for_scoring(transcript)
print("raw len", len(transcript), "clean len", len(clean))
ctx_raw = detect_call_context(transcript, fn)
ctx_clean = detect_call_context(clean, fn)
print("raw is_collections", ctx_raw["is_collections"])
print("clean is_collections", ctx_clean["is_collections"])
kpis_clean = detect_call_kpis(clean, filename_hint=fn)
print("clean kpis is_collections", kpis_clean.get("is_collections"))
result = apply_phase1_scoring({}, clean, fn)
print("phase1 score", result["total_score"], result.get("compliance_flags"))
print("ctx in calibration", result.get("_scoring_calibration", {}).get("is_collections"))
