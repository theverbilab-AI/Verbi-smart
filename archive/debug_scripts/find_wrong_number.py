import sqlite3
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from scoring_rules import detect_call_context, _evaluate_rpc_status, _transcript_turns

conn = sqlite3.connect("care.db")
t, fn = conn.execute(
    "SELECT transcript, filename FROM calls WHERE id='CALL-2F90045C'"
).fetchone()
ctx = detect_call_context(t, fn)
print("is_wrong_number", ctx["is_wrong_number"])
print("is_collections", ctx["is_collections"])
print("rpc", ctx["rpc_confirmed"])

wrong_number_cues = (
    "wrong number", "galat number", "not this person", "not him", "not her",
    "number change", "changed my number", "who is this", "don't know him",
    "don't know her", "no such person", "not available", "passed away",
    "deceased", "wrong party",
)
low = t.lower()
for c in wrong_number_cues:
    if c in low:
        idx = low.index(c)
        print("wrong cue:", c, "->", repr(t[max(0, idx - 60) : idx + len(c) + 60]))

turns = _transcript_turns(t)
rpc_a, rpc_c, loan = _evaluate_rpc_status(turns, wrong_number_cues)
print("evaluate_rpc", rpc_a, rpc_c, loan)
