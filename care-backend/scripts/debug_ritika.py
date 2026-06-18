import json
import sqlite3

conn = sqlite3.connect("care.db")
conn.row_factory = sqlite3.Row
rows = conn.execute(
    """
    SELECT id, filename, score, transcript, scores_breakdown, compliance_flags,
           ai_detection, analysis
    FROM calls
    WHERE id LIKE '%2F90045C%' OR filename LIKE '%RITIKA%' OR filename LIKE '%addadef1%'
    ORDER BY uploaded_at DESC LIMIT 3
    """
).fetchall()
for r in rows:
    d = dict(r)
    print("===", d["id"], d["filename"], "score", d["score"])
    print("flags", d["compliance_flags"])
    print("ai_det", d["ai_detection"])
    print("breakdown", d["scores_breakdown"])
    a = json.loads(d["analysis"] or "{}") if d.get("analysis") else {}
    print("summary", str(a.get("summary", ""))[:250])
    print("opening", a.get("opening_audit"))
    t = d["transcript"] or ""
    print("transcript len", len(t))
    print("first 500:", t[:500])
    print("last 500:", t[-500:])
