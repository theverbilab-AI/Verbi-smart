#!/usr/bin/env python3
"""
Seed few-shot scoring examples for Sarvam LLM prompts.

Usage (from care-backend/):
  python scripts/seed_scoring_examples.py --golden     # curated golden set (no DB)
  python scripts/seed_scoring_examples.py --from-db    # best processed calls in DB
  python scripts/seed_scoring_examples.py --golden --from-db --merge
"""

from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from processor import (  # noqa: E402
    TRAINING_EXAMPLES_PATH,
    _load_scoring_training_examples,
    append_scoring_training_example,
    seed_scoring_examples_from_calls,
)
from scoring_rules import detect_call_kpis, run_hybrid_scoring  # noqa: E402

GOLDEN_SCENARIOS: list[tuple[str, list[str], str]] = [
    (
        "golden-rpc-yes-tell-me",
        ["rpc", "opening", "collections"],
        """Agent: Good morning, this call is recorded for quality. This is Rahul calling from Tala collections.
Customer: Yes, tell me.
Agent: Am I speaking with Mr Sharma?
Customer: Haan ji, main bol raha hu.""",
    ),
    (
        "golden-ptp-kal-karunga",
        ["ptp", "collections", "financial_hardship"],
        """Agent: Sir, your EMI of Rs 8500 is overdue by 15 days. Can you pay today?
Customer: Abhi paisa nahi hai, salary ke baad kal karunga UPI se.
Agent: Noted, I will record PTP for tomorrow via UPI.""",
    ),
    (
        "golden-third-party-safe",
        ["third_party", "third_party_safe", "collections"],
        """Agent: Good afternoon, may I speak with Mr Verma?
Customer: Main unki behen bol rahi hoon, wo ghar pe nahi hai, bahar gaya hai.
Agent: Please ask him to call us back. I will not share account details.""",
    ),
    (
        "golden-third-party-breach",
        ["third_party", "third_party_breach", "compliance"],
        """Agent: Is Mr Patel available?
Customer: Mummy bol rahi hoon, beta bahar gaya hai.
Agent: Unka loan outstanding Rs 12000 hai, EMI pending hai.""",
    ),
    (
        "golden-app-payment-issue",
        ["app_payment_issue", "app_issue", "collections"],
        """Agent: Can you pay through the app link today?
Customer: Link nahi khul raha, UPI fail ho raha hai bar bar.
Agent: Try NEFT or visit branch, I will send alternate link.""",
    ),
    (
        "golden-financial-hardship",
        ["financial_hardship", "collections"],
        """Agent: Why has payment not been made this month?
Customer: Mera job chala gaya, naukri nahi hai abhi, paisa nahi hai.
Agent: I understand. When can you arrange partial payment?""",
    ),
    (
        "golden-wrong-number",
        ["wrong_number", "other"],
        """Agent: Am I speaking with Mr Kumar regarding loan?
Customer: Galat number hai, wrong number, maine koi loan nahi liya.""",
    ),
    (
        "golden-marathi-opening",
        ["rpc", "opening", "marathi"],
        """Agent: Mi Tala collections madhun bolto aahe, ha call record hoto.
Customer: Ho, bolta.
Agent: Tumhi Mr Deshmukh ka?
Customer: Ho, mi bolto.""",
    ),
]


def _expected_json_from_rules(transcript: str) -> dict:
    """Build expected scorer JSON using hybrid rules (deterministic ground truth)."""
    llm_stub = {
        "scores": {},
        "compliance_flags": [],
        "ai_detection": ["NONE"],
        "disposition": "OTHER",
    }
    result = run_hybrid_scoring(llm_stub, transcript)
    kpis = detect_call_kpis(transcript)
    return {
        "scores": result.get("scores") or {},
        "total_score": result.get("total_score") or 0,
        "total_score_pct": result.get("total_score_pct") or 0,
        "grade": result.get("grade") or "Poor",
        "critical_fail": bool(result.get("critical_fail")),
        "ptp_detected": bool(result.get("ptp_detected")),
        "ptp_amount": result.get("ptp_amount"),
        "ptp_date": result.get("ptp_date"),
        "ptp_mode": result.get("ptp_mode"),
        "disposition": result.get("disposition") or "OTHER",
        "risk_level": result.get("risk_level") or "LOW",
        "ai_detection": result.get("ai_detection") or ["NONE"],
        "ai_suggestion": result.get("ai_suggestion") or kpis.get("ai_suggestion") or "",
        "compliance_flags": result.get("compliance_flags") or ["NONE"],
        "confidence": int(result.get("confidence") or kpis.get("confidence") or 80),
        "summary": result.get("summary") or "",
        "key_issues": result.get("key_issues") or [],
        "coaching_tip": result.get("coaching_tip") or "",
    }


def seed_golden(*, merge: bool = False) -> int:
    if not merge and os.path.isfile(TRAINING_EXAMPLES_PATH):
        os.remove(TRAINING_EXAMPLES_PATH)
    existing_ids = {str(x.get("id")) for x in _load_scoring_training_examples()} if merge else set()
    added = 0
    for example_id, tags, transcript in GOLDEN_SCENARIOS:
        if example_id in existing_ids:
            continue
        append_scoring_training_example({
            "id": example_id,
            "tags": tags,
            "transcript": transcript.strip(),
            "expected_json": _expected_json_from_rules(transcript),
        })
        added += 1
        print(f"  + {example_id} ({', '.join(tags[:3])})")
    return added


def seed_from_db(min_score_pct: int, max_examples: int, merge: bool) -> dict:
    from database import init_db, list_calls

    init_db()
    calls = list_calls(status="processed", limit=500)
    return seed_scoring_examples_from_calls(
        calls,
        min_score_pct=min_score_pct,
        max_examples=max_examples,
        merge=merge,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Seed few-shot scoring examples")
    parser.add_argument("--golden", action="store_true", help="Add curated golden scenarios")
    parser.add_argument("--from-db", action="store_true", help="Add best calls from database")
    parser.add_argument("--merge", action="store_true", help="Append without wiping existing file")
    parser.add_argument("--min-score-pct", type=int, default=70)
    parser.add_argument("--max-examples", type=int, default=12)
    args = parser.parse_args()

    if not args.golden and not args.from_db:
        args.golden = True

    print(f"Target: {TRAINING_EXAMPLES_PATH}")
    if args.golden:
        print("Seeding golden examples…")
        n = seed_golden(merge=args.merge)
        print(f"Golden added: {n}")

    if args.from_db:
        print("Seeding from DB…")
        summary = seed_from_db(args.min_score_pct, args.max_examples, args.merge or args.golden)
        print(json.dumps(summary, indent=2))

    total = len(_load_scoring_training_examples())
    print(f"Total examples in file: {total}")
    return 0 if total else 1


if __name__ == "__main__":
    raise SystemExit(main())
