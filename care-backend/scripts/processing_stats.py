#!/usr/bin/env python3
"""Estimate processing duration for processed calls (load-test helper)."""
from __future__ import annotations

import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from database import init_db, list_calls  # noqa: E402


def _parse(ts: str) -> datetime | None:
    if not ts:
        return None
    try:
        return datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    except Exception:
        return None


def main():
    init_db()
    calls = list_calls(status="processed", limit=2000)
    deltas = []
    sizes = []
    for c in calls:
        u, p = _parse(c.get("uploaded_at")), _parse(c.get("processed_at"))
        if u and p:
            sec = max(0, (p - u).total_seconds())
            if 5 < sec < 3600:
                deltas.append(sec)
        fs = int(c.get("file_size") or 0)
        if fs > 0:
            sizes.append(fs)

    print(f"Processed calls: {len(calls)}")
    if deltas:
        deltas.sort()
        avg = sum(deltas) / len(deltas)
        p50 = deltas[len(deltas) // 2]
        p90 = deltas[int(len(deltas) * 0.9)]
        print(f"Timing samples: {len(deltas)}")
        print(f"  avg: {avg:.0f}s ({avg/60:.1f} min)")
        print(f"  p50: {p50:.0f}s ({p50/60:.1f} min)")
        print(f"  p90: {p90:.0f}s ({p90/60:.1f} min)")
        print(f"  min/max: {deltas[0]:.0f}s / {deltas[-1]:.0f}s")
    else:
        print("No uploaded_at/processed_at pairs — use estimates below.")
    if sizes:
        print(f"File sizes: avg {sum(sizes)/len(sizes)/1e6:.1f} MB, max {max(sizes)/1e6:.1f} MB")


if __name__ == "__main__":
    main()
