"""
Structured audit-pipeline logging (upload → STT → score → DB).

Persists a rolling log on call.analysis.pipeline_log for ops debugging.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def append_pipeline_log(
    update_call_fn,
    call_id: str,
    event: str,
    *,
    status: str | None = None,
    detail: str | None = None,
    error: str | None = None,
    extra: dict[str, Any] | None = None,
) -> None:
    """Append one pipeline event and optionally update call status."""
    entry: dict[str, Any] = {"at": _now_iso(), "event": event}
    if status:
        entry["status"] = status
    if detail:
        entry["detail"] = detail[:500]
    if error:
        entry["error"] = str(error)[:800]
    if extra:
        entry.update(extra)

    line = (
        f"[AUDIT-PIPELINE] {call_id} {event}"
        + (f" status={status}" if status else "")
        + (f" {detail}" if detail else "")
        + (f" ERROR={error}" if error else "")
    )
    print(line, flush=True)

    payload: dict[str, Any] = {}
    if status:
        payload["status"] = status
    if error:
        payload["error"] = str(error)[:800]

    try:
        from database import get_call

        row = get_call(call_id) or {}
        analysis = row.get("analysis") or {}
        if isinstance(analysis, str):
            try:
                analysis = json.loads(analysis) if analysis.strip() else {}
            except Exception:
                analysis = {}
        log = list(analysis.get("pipeline_log") or [])
        log.append(entry)
        analysis["pipeline_log"] = log[-40:]
        analysis["pipeline_last_event"] = event
        analysis["pipeline_last_at"] = entry["at"]
        payload["analysis"] = analysis
        update_call_fn(call_id, payload)
    except Exception as exc:
        print(f"[AUDIT-PIPELINE] {call_id} log persist skipped: {exc}", flush=True)
