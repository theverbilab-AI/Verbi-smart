import sqlite3
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

conn = sqlite3.connect("care.db")
t = conn.execute("SELECT transcript FROM calls WHERE id='CALL-2F90045C'").fetchone()[0]
low = t.lower()
cues = [
    "wrong number", "galat number", "not this person", "not him", "not her",
    "number change", "who is this", "no such person", "wrong party", "brother",
]
for c in cues:
    if c in low:
        idx = low.index(c)
        print(c, "->", repr(t[max(0, idx - 50) : idx + len(c) + 50]))
