#!/usr/bin/env python3
"""One-off: keep newest N calls in DB, delete the rest. Run from care-backend/."""

from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database import DB_TYPE, init_db, purge_calls  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Purge old CARE call records from the database.")
    parser.add_argument("--keep", type=int, default=30, help="Number of newest calls to keep (default 30)")
    parser.add_argument("--org-id", default="org_default", help="Organisation id")
    parser.add_argument("--dry-run", action="store_true", help="Show counts only, do not delete")
    parser.add_argument("--yes", action="store_true", help="Skip confirmation prompt")
    args = parser.parse_args()

    init_db()
    print(f"Database: {DB_TYPE}")

    preview = purge_calls(org_id=args.org_id, keep=args.keep, dry_run=True)
    print(f"Total calls: {preview['total_before']}")
    print(f"Would keep: {preview['kept']}")
    print(f"Would delete: {preview['deleted']}")

    if preview["deleted"] == 0:
        print("Nothing to delete.")
        return 0

    if not args.dry_run and not args.yes:
        answer = input(f"Delete {preview['deleted']} call(s)? Type yes: ").strip().lower()
        if answer != "yes":
            print("Aborted.")
            return 1

    result = purge_calls(org_id=args.org_id, keep=args.keep, dry_run=args.dry_run)
    print(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
