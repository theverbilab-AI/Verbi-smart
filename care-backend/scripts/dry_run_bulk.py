#!/usr/bin/env python3
"""
Sarvam-only bulk dry run: purge old calls, upload/process N recordings with full scoring.

Usage (from care-backend/):
  python scripts/dry_run_bulk.py --purge-all --yes --limit 25
  python scripts/dry_run_bulk.py --limit 25 --audio-dir "C:\\Users\\...\\Downloads\\calls"
  python scripts/dry_run_bulk.py --mode api --api https://api.care.verbilab.com --limit 25

Requires SARVAM_API_KEY in .env. Set CARE_MAX_PARALLEL_PROCESSING=4 for ~20–30 queued calls.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv

load_dotenv()

AUDIO_EXTS = {".mp3", ".wav", ".m4a", ".ogg", ".flac", ".aac", ".webm"}
UPLOAD_FOLDER = os.path.join(os.path.dirname(os.path.dirname(__file__)), "uploads")


def _collect_audio(paths: list[str], limit: int) -> list[Path]:
    found: list[Path] = []
    seen: set[str] = set()
    for raw in paths:
        p = Path(raw)
        if p.is_file() and p.suffix.lower() in AUDIO_EXTS:
            key = str(p.resolve()).lower()
            if key not in seen:
                seen.add(key)
                found.append(p)
        elif p.is_dir():
            for f in sorted(p.rglob("*")):
                if f.suffix.lower() in AUDIO_EXTS and f.is_file():
                    key = str(f.resolve()).lower()
                    if key not in seen:
                        seen.add(key)
                        found.append(f)
    found.sort(key=lambda x: x.name.lower())
    return found[:limit]


def _parse_meta(filename: str) -> dict[str, str]:
    from agent_parse import parse_agent_loan_from_filename

    meta = parse_agent_loan_from_filename(filename)
    return {
        "agent_id": meta.get("agent_id") or "",
        "loan_id": meta.get("loan_id") or "",
    }


def _purge(org_id: str, keep: int, yes: bool) -> dict:
    from database import init_db, purge_calls

    init_db()
    preview = purge_calls(org_id=org_id, keep=keep, dry_run=True)
    print(f"Purge preview: total={preview['total_before']} delete={preview['deleted']} keep={preview['kept']}")
    if preview["deleted"] == 0:
        return preview
    if not yes:
        raise SystemExit("Aborted — pass --yes to confirm purge.")
    return purge_calls(org_id=org_id, keep=keep, dry_run=False)


def _save_upload(src: Path, call_id: str) -> tuple[str, int]:
    os.makedirs(UPLOAD_FOLDER, exist_ok=True)
    safe = "".join(c if c.isalnum() or c in "._- " else "_" for c in src.name)
    dest = os.path.join(UPLOAD_FOLDER, f"{call_id}_{safe}")
    shutil.copy2(src, dest)
    return dest, os.path.getsize(dest)


def _queue_call_direct(src: Path, org_id: str, audit_mode: str) -> str:
    from database import save_call, update_call
    from processor import process_call_async

    try:
        from storage import archive_local_audio
    except Exception:
        archive_local_audio = None  # type: ignore

    call_id = f"CALL-{uuid.uuid4().hex[:8].upper()}"
    save_path, file_size = _save_upload(src, call_id)
    meta = _parse_meta(src.name)
    record = {
        "id": call_id,
        "org_id": org_id,
        "filename": src.name,
        "file_path": save_path,
        "file_size": file_size,
        "source": "dry_run",
        "status": "queued",
        "uploaded_at": datetime.now(timezone.utc).isoformat(),
        "agent_id": meta.get("agent_id") or None,
        "loan_id": meta.get("loan_id") or None,
        "analysis": {"audit_mode": audit_mode},
    }
    if archive_local_audio:
        try:
            s3_uri = archive_local_audio(save_path, call_id, src.name)
            if s3_uri:
                record["source_uri"] = s3_uri
        except Exception as exc:
            print(f"[dry-run] S3 archive skipped for {call_id}: {exc}", flush=True)
    save_call(record)
    process_call_async(call_id, save_path, record, lambda cid, f: update_call(cid, f))
    return call_id


def _login_api(base: str, email: str, password: str) -> str:
    import requests

    r = requests.post(f"{base}/api/auth/login", json={"email": email, "password": password}, timeout=30)
    r.raise_for_status()
    return r.json()["token"]


def _queue_call_api(base: str, token: str, src: Path, audit_mode: str) -> str:
    import requests

    meta = _parse_meta(src.name)
    data = {"audit_mode": audit_mode}
    if meta.get("agent_id"):
        data["agent_id"] = meta["agent_id"]
    if meta.get("loan_id"):
        data["loan_id"] = meta["loan_id"]
    with open(src, "rb") as f:
        r = requests.post(
            f"{base}/api/v1/calls/ingest",
            headers={"Authorization": f"Bearer {token}"},
            files={"file": (src.name, f, "application/octet-stream")},
            data=data,
            timeout=120,
        )
    r.raise_for_status()
    return r.json()["call_id"]


def _poll_calls(call_ids: list[str], timeout_sec: int) -> list[dict]:
    from database import get_call, init_db

    init_db()
    deadline = time.time() + timeout_sec
    pending = set(call_ids)
    results: dict[str, dict] = {}

    while pending and time.time() < deadline:
        done_this_round: list[str] = []
        for cid in sorted(pending):
            row = get_call(cid) or {}
            st = str(row.get("status") or "").lower()
            if st in {"processed", "failed"}:
                results[cid] = row
                done_this_round.append(cid)
                score = row.get("score")
                disp = row.get("disposition")
                err = (row.get("error") or "")[:80]
                print(f"  [{st}] {cid} score={score} disp={disp} {err}", flush=True)
        for cid in done_this_round:
            pending.discard(cid)
        if pending:
            print(f"  ... waiting on {len(pending)} call(s)", flush=True)
            time.sleep(8)

    for cid in pending:
        results[cid] = get_call(cid) or {"id": cid, "status": "timeout"}
    return [results.get(cid, {"id": cid, "status": "missing"}) for cid in call_ids]


def _summarize(rows: list[dict]) -> dict:
    processed = [r for r in rows if r.get("status") == "processed"]
    failed = [r for r in rows if r.get("status") == "failed"]
    other = [r for r in rows if r.get("status") not in {"processed", "failed"}]
    scores = [int(r.get("score") or 0) for r in processed]
    return {
        "total": len(rows),
        "processed": len(processed),
        "failed": len(failed),
        "pending_or_timeout": len(other),
        "avg_score": round(sum(scores) / len(scores), 2) if scores else None,
        "min_score": min(scores) if scores else None,
        "max_score": max(scores) if scores else None,
        "failures": [
            {"id": r.get("id"), "error": (r.get("error") or "")[:200]}
            for r in failed + other
        ],
        "samples": [
            {
                "id": r.get("id"),
                "filename": r.get("filename"),
                "score": r.get("score"),
                "disposition": r.get("disposition"),
                "grade": r.get("grade"),
                "ptp_detected": r.get("ptp_detected"),
            }
            for r in processed[:10]
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Sarvam bulk dry run with scoring")
    parser.add_argument("--limit", type=int, default=25, help="Max calls to process (default 25)")
    parser.add_argument(
        "--audio-dir",
        action="append",
        default=[r"C:\Users\SIDDHANTH REMMA\Downloads\calls"],
        help="Folder(s) with .mp3/.wav recordings (repeatable)",
    )
    parser.add_argument("--purge-all", action="store_true", help="Delete ALL existing calls before run")
    parser.add_argument("--keep", type=int, default=0, help="Keep N newest calls when purging (default 0 with --purge-all)")
    parser.add_argument("--yes", action="store_true", help="Confirm destructive purge")
    parser.add_argument("--org-id", default="org_default")
    parser.add_argument("--audit-mode", default="collections", choices=["collections", "sales"])
    parser.add_argument("--mode", default="direct", choices=["direct", "api"])
    parser.add_argument("--api", default=os.getenv("CARE_API_URL", "http://127.0.0.1:5000"))
    parser.add_argument("--email", default=os.getenv("CARE_DRY_RUN_EMAIL", "theverbilab@gmail.com"))
    parser.add_argument("--password", default=os.getenv("CARE_DRY_RUN_PASSWORD", ""))
    parser.add_argument("--timeout", type=int, default=3600, help="Wait up to N seconds for processing")
    parser.add_argument("--report", default="", help="Write JSON summary to this path")
    args = parser.parse_args()

    if not os.getenv("SARVAM_API_KEY"):
        print("ERROR: SARVAM_API_KEY not set in care-backend/.env", file=sys.stderr)
        return 1

    files = _collect_audio(args.audio_dir, args.limit)
    if not files:
        print("ERROR: No audio files found.", file=sys.stderr)
        return 1
    if len(files) < args.limit:
        print(f"WARNING: Only {len(files)} audio file(s) found (requested {args.limit}).")

    if args.purge_all:
        keep = 0 if args.purge_all else args.keep
        _purge(args.org_id, keep=keep, yes=args.yes)
    elif args.keep > 0:
        _purge(args.org_id, keep=args.keep, yes=args.yes)

    parallel = int(os.getenv("CARE_MAX_PARALLEL_PROCESSING", "4"))
    print(f"=== Sarvam dry run: {len(files)} call(s), parallel<={parallel}, mode={args.mode} ===")

    call_ids: list[str] = []
    if args.mode == "api":
        if not args.password:
            print("ERROR: Set --password or CARE_DRY_RUN_PASSWORD for API mode.", file=sys.stderr)
            return 1
        token = _login_api(args.api.rstrip("/"), args.email, args.password)
        for src in files:
            cid = _queue_call_api(args.api.rstrip("/"), token, src, args.audit_mode)
            call_ids.append(cid)
            print(f"  queued {cid} <- {src.name}", flush=True)
    else:
        from database import init_db

        init_db()
        for src in files:
            cid = _queue_call_direct(src, args.org_id, args.audit_mode)
            call_ids.append(cid)
            print(f"  queued {cid} <- {src.name}", flush=True)

    print(f"\n=== Processing (timeout {args.timeout}s) ===")
    rows = _poll_calls(call_ids, args.timeout)
    summary = _summarize(rows)
    summary["call_ids"] = call_ids
    summary["generated_at"] = datetime.now(timezone.utc).isoformat()

    print("\n=== SUMMARY ===")
    print(json.dumps(summary, indent=2))
    report_path = args.report or os.path.join(
        os.path.dirname(__file__), "DRY_RUN_REPORT.json"
    )
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)
    print(f"\nReport: {report_path}")

    if summary["failed"] or summary["pending_or_timeout"]:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
