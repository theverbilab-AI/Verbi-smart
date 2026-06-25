"""
Local end-to-end test harness for VERBICARE (Collections + Sales QA).

Runs the REAL pipeline on real audio files:
  audio -> Sarvam STT -> canonical speaker attribution -> scoring -> validation
using an in-memory capture (no RDS writes; S3 archive side-effects disabled).

Then verifies:
  1. Collections checklist (speaker attribution, PTP, disposition, summary, review)
  2. Sales checklist (16 KPIs, /100, evidence per KPI, no hallucination, summary)
  3. Regression / consistency (process vs read-API vs reprocess-API)

Writes a Markdown report to scripts/E2E_LOCAL_REPORT.md.

Usage:  python scripts/e2e_local_test.py
"""
import os
import sys
import json
import time
import traceback

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from dotenv import load_dotenv  # noqa: E402

load_dotenv()

# Disable S3 archive side-effects so the local test doesn't upload anything.
for _k in ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "S3_BUCKET"):
    os.environ.pop(_k, None)

DL = r"C:\Users\SIDDHANTH REMMA\Downloads"
CALLS_DIR = os.path.join(DL, "calls")

# Real audio supplied by the user (collections-style recovery calls).
COLLECTIONS_FILES = [
    os.path.join(CALLS_DIR, "AFILAPLPL15148-RITA.wav"),
    os.path.join(CALLS_DIR, "1982389-MANSI.mp3"),
    os.path.join(DL, "1899703-RITIKA.wav.wav"),
]
SALES_FILES = [
    os.path.join(CALLS_DIR, "1986509-GAURI.mp4"),
]

REPORT = os.path.join(os.path.dirname(__file__), "E2E_LOCAL_REPORT.md")

results = {"passed": [], "failed": [], "sections": []}
_log_lines = []


def log(s=""):
    print(s, flush=True)
    _log_lines.append(s)


def check(name, cond, detail=""):
    if cond:
        results["passed"].append(name)
        log(f"  PASS  {name}")
    else:
        results["failed"].append(f"{name} :: {detail}")
        log(f"  FAIL  {name}  {detail}")
    return cond


def run_pipeline(path, audit_mode):
    """Run the real pipeline on one file; return the captured final record."""
    from processor import process_call

    call_id = "E2E-" + os.path.splitext(os.path.basename(path))[0].upper()[:24]
    record = {}

    def capture(cid, fields):
        if fields:
            record.update(fields)

    calls_db = {
        "filename": os.path.basename(path),
        "file_path": path,
        "analysis": {"audit_mode": audit_mode},
    }
    t0 = time.time()
    process_call(call_id, path, calls_db, capture)
    record["_elapsed_s"] = round(time.time() - t0, 1)
    record["id"] = call_id
    # Emulate the DB read round-trip: _safe_update_call serialises JSON columns
    # to strings on write; get_call() deserialises them back to objects on read.
    _normalize_record(record)
    return call_id, record


def _normalize_record(rec):
    """Parse JSON-column string values back to objects, like database.get_call()."""
    try:
        from database import JSON_FIELDS
        fields = JSON_FIELDS
    except Exception:
        fields = {"analysis", "scores_breakdown", "compliance_flags",
                  "strengths", "key_issues", "ai_detection", "dispositions"}
    for k in fields:
        v = rec.get(k)
        if isinstance(v, str):
            try:
                rec[k] = json.loads(v)
            except Exception:
                pass
    return rec


# ───────────────────────── Collections checklist ─────────────────────────

def verify_collections(name, rec):
    log(f"\n--- Collections: {name} ({rec.get('_elapsed_s')}s) ---")
    ok = rec.get("status") == "processed"
    check(f"[{name}] processed (status=processed)", ok, f"status={rec.get('status')} err={rec.get('error')}")
    if not ok:
        return
    analysis = rec.get("analysis") or {}

    transcript = (rec.get("transcript") or "").strip()
    check(f"[{name}] transcript present", len(transcript) > 40, f"len={len(transcript)}")

    qa0 = analysis.get("qa_validation") or {}
    review = bool(qa0.get("review_required"))

    turns = analysis.get("speaker_turns") or []
    has_both = {str(t.get("speaker")).lower() for t in turns}
    check(f"[{name}] speaker attribution produced turns", len(turns) >= 2, f"turns={len(turns)}")
    # Both speakers should normally be present; if attribution degenerates to one
    # speaker (e.g. failed diarization / language issue) the call MUST be flagged
    # for manual review rather than silently mis-labelled.
    both = {"agent", "customer"} <= has_both
    check(f"[{name}] both speakers attributed OR review flagged", both or review,
          f"speakers={has_both} review={review}")
    if not both:
        log(f"    NOTE: single-speaker attribution -> review_required={review} (safe fallback)")
    conf_ok = all(isinstance(t.get("confidence"), (int, float)) for t in turns) and bool(turns)
    check(f"[{name}] every turn has confidence", conf_ok)

    # PTP detection: field must be a definite value (0/1 or bool) — detected or not.
    ptp = rec.get("ptp_detected")
    ran = ptp in (0, 1, True, False)
    check(f"[{name}] PTP detection produced a definite result", ran, f"ptp_detected={ptp!r}")
    if ptp in (1, True):
        check(f"[{name}] PTP has date or amount", bool(rec.get("ptp_date") or rec.get("ptp_amount")))

    disp = rec.get("disposition")
    check(f"[{name}] disposition set", bool(disp), f"disposition={disp}")

    summary = (rec.get("summary") or "").strip()
    check(f"[{name}] summary non-empty", len(summary) > 10, f"summary='{summary[:60]}'")
    check(f"[{name}] summary not a prompt leak", "JSON" not in summary.upper() or "AI JSON" not in summary)

    qa = analysis.get("qa_validation") or {}
    check(f"[{name}] review_required present (bool)", isinstance(qa.get("review_required"), bool),
          f"qa={qa.get('review_required')}")

    log(f"    score={rec.get('score')}/20 grade={rec.get('grade')} disp={disp} "
        f"ptp={ptp} review={qa.get('review_required')}")


# ───────────────────────── Sales checklist ─────────────────────────

EXPECTED_SALES_IDS = {
    "opening", "qualifying", "product_knowledge", "exemptions", "advance_closing",
    "zell_training", "pricing", "whatsapp_email", "referral", "closing",
    "sales_techniques", "objection_handling", "closing_followup", "soft_skills",
    "previous_call_notes", "fatal",
}


def verify_sales(name, audit, real_audio=True):
    log(f"\n--- Sales: {name} ---")
    kpis = audit.get("kpis") or []
    ids = {k["id"] for k in kpis}
    check(f"[{name}] all 16 KPIs present", ids == EXPECTED_SALES_IDS, f"missing={EXPECTED_SALES_IDS - ids}")

    pct = audit.get("total_pct")
    score = audit.get("total_score")
    check(f"[{name}] score out of 100 (0..100)", isinstance(score, (int, float)) and 0 <= score <= 100,
          f"score={score}")
    check(f"[{name}] total_pct present (0..100)", isinstance(pct, (int, float)) and 0 <= pct <= 100, f"pct={pct}")

    # NO HALLUCINATION: any Done/Partial KPI MUST carry transcript evidence.
    hallucinated = [
        k["id"] for k in kpis
        if k["id"] != "fatal" and k["status"] in ("Done", "Partial")
        and not (k.get("evidence") or k.get("all_evidence"))
    ]
    check(f"[{name}] no hallucinated KPI (evidence backs every scored KPI)", not hallucinated,
          f"offenders={hallucinated}")

    # Not Done KPIs must declare the no-evidence reason.
    bad_reason = [
        k["id"] for k in kpis
        if k["id"] != "fatal" and k["status"] == "Not Done"
        and "No transcript evidence found" not in (k.get("reason") or "")
        and "not assessable" not in (k.get("reason") or "")
    ]
    check(f"[{name}] Not-Done KPIs cite no-evidence reason", not bad_reason, f"offenders={bad_reason}")

    sm = audit.get("summary") or {}
    for field in ("executive_summary", "strengths", "missed_opportunities",
                  "coaching_suggestions", "fatal_errors", "sales_probability", "customer_intent"):
        check(f"[{name}] summary.{field} present", field in sm and sm[field] not in (None, "", []))
    check(f"[{name}] recommendations present", isinstance(audit.get("recommendations"), list))
    check(f"[{name}] review_required present (bool)", isinstance(audit.get("review_required"), bool))

    if real_audio:
        # A collections recovery call scored as SALES should be mostly Not Done
        # (proves the engine does not invent sales behaviour).
        done = [k for k in kpis if k["id"] != "fatal" and k["status"] != "Not Done"]
        log(f"    (real non-sales audio) scored={score}/100 done/partial KPIs={len(done)} review={audit.get('review_required')}")

    log(f"    score={score}/100 grade={audit.get('grade')} prob={audit.get('sales_probability')} "
        f"intent={audit.get('customer_intent')} review={audit.get('review_required')}")


# ───────────────────────── Consistency (read + reprocess APIs) ─────────────────────────

def verify_consistency(name, call_id, rec):
    log(f"\n--- Consistency: {name} ---")
    import app
    from processor import reprocess_call_from_existing

    base_record = dict(rec)

    # READ API path
    try:
        read = app._enrich_call_payload(dict(base_record))
        same_grade = read.get("grade") == base_record.get("grade")
        check(f"[{name}] read API grade stable", same_grade,
              f"{base_record.get('grade')} -> {read.get('grade')}")
        if (base_record.get("analysis") or {}).get("audit_mode") == "sales":
            a1 = (base_record.get("analysis") or {}).get("sales_kpi", {}).get("total_score")
            a2 = (read.get("analysis") or {}).get("sales_kpi", {}).get("total_score")
            check(f"[{name}] read API sales score stable", a1 == a2, f"{a1} -> {a2}")
    except Exception as e:
        check(f"[{name}] read API no exception", False, repr(e))

    # REPROCESS API path
    try:
        rp = {}
        reprocess_call_from_existing(call_id, dict(base_record), lambda c, f: rp.update(f or {}))
        check(f"[{name}] reprocess no exception", rp.get("status") == "processed",
              f"status={rp.get('status')} err={rp.get('error')}")
        check(f"[{name}] reprocess grade stable", rp.get("grade") == base_record.get("grade"),
              f"{base_record.get('grade')} -> {rp.get('grade')}")
    except Exception as e:
        check(f"[{name}] reprocess no exception", False, repr(e))


# ───────────────────────── Main ─────────────────────────

def main():
    log("# VERBICARE — Local End-to-End Test")
    log(f"Started: {time.strftime('%Y-%m-%d %H:%M:%S')}")
    log(f"RULES_ONLY_SCORING={os.getenv('CARE_RULES_ONLY_SCORING')}  SARVAM_KEY={'set' if os.getenv('SARVAM_API_KEY') else 'MISSING'}")

    collections_recs = {}
    sales_recs = {}

    # 1) Collections — real pipeline
    log("\n## 1. Collections QA (real audio)")
    for path in COLLECTIONS_FILES:
        nm = os.path.basename(path)
        if not os.path.isfile(path):
            check(f"[{nm}] file exists", False, path)
            continue
        try:
            cid, rec = run_pipeline(path, "collections")
            collections_recs[cid] = (nm, rec)
            verify_collections(nm, rec)
        except Exception as e:
            check(f"[{nm}] pipeline no exception", False, repr(e))
            log(traceback.format_exc())

    # 2) Sales — real pipeline on supplied file
    log("\n## 2. Sales QA (real audio, sales mode)")
    for path in SALES_FILES:
        nm = os.path.basename(path)
        if not os.path.isfile(path):
            check(f"[{nm}] file exists", False, path)
            continue
        try:
            cid, rec = run_pipeline(path, "sales")
            sales_recs[cid] = (nm, rec)
            audit = (rec.get("analysis") or {}).get("sales_kpi") or {}
            verify_sales(nm, audit, real_audio=True)
        except Exception as e:
            check(f"[{nm}] pipeline no exception", False, repr(e))
            log(traceback.format_exc())

    # 2b) Sales engine on real collections transcripts -> proves NO HALLUCINATION
    log("\n## 2b. Sales engine on real (non-sales) transcripts — no-hallucination proof")
    from processor import _score_sales
    for cid, (nm, rec) in collections_recs.items():
        tr = (rec.get("transcript") or "").strip()
        if not tr:
            continue
        audit = (_score_sales(tr) or {}).get("sales_kpi") or {}
        verify_sales(f"{nm} as-sales", audit, real_audio=True)

    # 2c) Sales engine on a known-good synthetic sales call -> positive path
    log("\n## 2c. Sales engine on synthetic positive sales call")
    try:
        from scripts.test_sales_kpi import GOOD_CALL
        from audit_modes.sales_kpi import score_sales_call
        good = score_sales_call(GOOD_CALL)
        verify_sales("synthetic GOOD_CALL", good, real_audio=False)
        check("[synthetic] positive call scores >= 60%", good["total_pct"] >= 60, f"pct={good['total_pct']}")
    except Exception as e:
        check("[synthetic] sales positive path", False, repr(e))

    # 3) Consistency for one collections + one sales call
    log("\n## 3. Regression / consistency (process vs read vs reprocess)")
    if collections_recs:
        cid, (nm, rec) = next(iter(collections_recs.items()))
        verify_consistency(nm, cid, rec)
    if sales_recs:
        cid, (nm, rec) = next(iter(sales_recs.items()))
        verify_consistency(nm, cid, rec)

    # Summary
    log("\n## Result")
    log(f"PASSED: {len(results['passed'])}")
    log(f"FAILED: {len(results['failed'])}")
    for f in results["failed"]:
        log(f"  - {f}")

    with open(REPORT, "w", encoding="utf-8") as fh:
        fh.write("\n".join(_log_lines))
    log(f"\nReport written: {REPORT}")
    return 1 if results["failed"] else 0


if __name__ == "__main__":
    sys.exit(main())
