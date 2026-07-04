#!/usr/bin/env python3
"""Print dry-run / bulk upload status from the active database."""
from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dotenv import load_dotenv

load_dotenv()

from database import init_db, list_calls  # noqa: E402


def main() -> int:
    init_db()
    calls = sorted(list_calls(limit=500), key=lambda c: c.get("uploaded_at") or "", reverse=True)
    rows = []
    for c in calls:
        rows.append(
            {
                "id": c.get("id"),
                "filename": c.get("filename"),
                "status": c.get("status"),
                "score": c.get("score"),
                "disposition": c.get("disposition"),
                "grade": c.get("grade"),
                "error": (c.get("error") or "")[:120],
            }
        )
    processed = [r for r in rows if r["status"] == "processed"]
    failed = [r for r in rows if r["status"] != "processed"]
    summary = {
        "total": len(rows),
        "processed": len(processed),
        "failed": len(failed),
        "avg_score": round(
            sum(float(r["score"] or 0) for r in processed) / len(processed), 2
        )
        if processed
        else None,
        "calls": rows,
    }
    print(json.dumps(summary, indent=2))
    out = os.path.join(os.path.dirname(__file__), "DRY_RUN_REPORT.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)
    print(f"\nWrote {out}")
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
