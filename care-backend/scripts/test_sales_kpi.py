"""
Automated tests for the Sales QA engine (audit_modes/sales_kpi.py).

Covers the KPIs management asked to verify explicitly:
  Opening, Qualification, Pricing, Referral, Soft skills,
  Fatal Errors, Objection handling, Closing
plus the NO-HALLUCINATION contract and the weight-sum = 100 invariant.

Run:  python scripts/test_sales_kpi.py
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from audit_modes.sales_kpi import (  # noqa: E402
    score_sales_call,
    validate_sales_audit,
    total_weight,
    SALES_KPIS,
)

PASS = 0
FAIL = 0


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  PASS  {name}")
    else:
        FAIL += 1
        print(f"  FAIL  {name}  {detail}")


def kpi(result, kpi_id):
    return next(k for k in result["kpis"] if k["id"] == kpi_id)


# A reasonably complete positive sales call.
GOOD_CALL = """
Agent: Hi, am I speaking with Rahul? You had enquired about the ACCA course on our webinar.
Customer: Yes, that's right.
Agent: Great. Before I explain, I want to know a few things about your profile. What is your highest qualification?
Customer: I am a B.Com graduate.
Agent: How did you come to know about this course? And where do you stay?
Customer: A friend suggested it. I stay in Pune.
Agent: How soon are you planning to start? Which attempt are you planning for? Are you a working professional?
Customer: Planning in 3 months, working currently.
Agent: Let me tell you about the course. ACCA stands for a globally recognised qualification, recognised in 180 countries. There are 13 papers and the passing rate is good. The scope is huge - you can work with Big 4 and MNCs abroad.
Customer: Okay.
Agent: Based on your B.Com, some papers are exempted so you don't have to write them.
Customer: Nice.
Agent: With Zell you get pre-learning, live lecture and recorded lectures, study material and books, doubt solving with 1:1 SME, mocks and unit tests, a student mentor, LMS access and placement assistance with our faculty.
Customer: Sounds good.
Agent: We have weekday and weekend batches. The fees is divided in two parts, the Zell fees and the body fees. The fees is inclusive of everything and we have EMI options.
Customer: How much is it?
Agent: I am sharing the details now. Is this your whatsapp number?
Customer: Yes.
Agent: Do you have any friends who might be interested? There is a referral bonus.
Customer: Maybe.
Agent: We have students like you from the same location who cleared it. One of my students got placed in a Big 4. Makes sense, right?
Customer: I will think, online classes may not suit me.
Agent: I understand, but our online sessions are interactive. Does that make sense?
Customer: Yes, clearer now.
Agent: The batch is starting soon and few seats are left, there is an early bird discount. I can understand your concern, that's a common one.
Customer: Okay.
Agent: Is there any doubt or queries? You can call on this number for further assistance. When should I call you on follow up - tomorrow at 5pm?
Customer: Tomorrow works.
"""

# A weak call: bare opening only, nothing else.
WEAK_CALL = """
Agent: Hello, am I speaking with Sir? You had enquired about ACCA.
Customer: Yes.
Agent: Ok bye.
Customer: Bye.
"""

# A fatal-error call: misleading claims.
FATAL_CALL = """
Agent: Hi, you had enquired about CMA. This is a no cost EMI and you get unlimited access forever.
Customer: Really?
Agent: Yes, and it is not a loan. Guaranteed job after the course.
Customer: Okay.
"""

# An empty-ish call to test no-hallucination (no agent KPI evidence).
EMPTY_CALL = """
Agent: Hmm.
Customer: Hmm.
"""


def main():
    print("== Sales QA KPI tests ==\n")

    # Invariant: weights sum to 100
    print("[Invariant] weight sum = 100")
    check("total weight == 100", total_weight() == 100, f"got {total_weight()}")

    good = score_sales_call(GOOD_CALL)
    weak = score_sales_call(WEAK_CALL)
    fatal = score_sales_call(FATAL_CALL)
    empty = validate_sales_audit(EMPTY_CALL, score_sales_call(EMPTY_CALL))

    print("\n[Opening]")
    check("opening done on good call", kpi(good, "opening")["status"] in ("Done", "Partial"))
    check("opening has evidence", bool(kpi(good, "opening")["evidence"]))

    print("\n[Qualification]")
    q = kpi(good, "qualifying")
    check("qualifying scored > 0", q["score"] > 0, f"score={q['score']}")
    check("qualifying has evidence", bool(q["evidence"]))

    print("\n[Pricing]")
    p = kpi(good, "pricing")
    check("pricing scored > 0", p["score"] > 0, f"score={p['score']}")
    check("pricing evidence present", bool(p["evidence"]))

    print("\n[Referral]")
    r = kpi(good, "referral")
    check("referral done", r["status"] in ("Done", "Partial"), f"status={r['status']}")

    print("\n[Soft skills]")
    s = kpi(good, "soft_skills")
    check("soft skills scored > 0", s["score"] > 0, f"score={s['score']}")
    # Pace must be flagged not-assessable, never auto-credited
    pace = next(sp for sp in s["subparams"] if sp["name"] == "Pace")
    check("pace not auto-credited", pace["marks"] == 0)

    print("\n[Objection handling]")
    o = kpi(good, "objection_handling")
    check("objection handling scored > 0", o["score"] > 0, f"score={o['score']}")

    print("\n[Closing]")
    c = kpi(good, "closing")
    cf = kpi(good, "closing_followup")
    check("closing scored > 0", c["score"] > 0, f"score={c['score']}")
    check("closing follow-up scored > 0", cf["score"] > 0, f"score={cf['score']}")

    print("\n[Fatal Errors]")
    f = kpi(fatal, "fatal")
    check("fatal triggered on misleading call", f.get("fatal_triggered") is True)
    check("fatal sets critical_fail", fatal["critical_fail"] is True)
    check("fatal grade is Critical Fail", fatal["grade"] == "Critical Fail")
    check("fatal review_required", fatal["review_required"] is True)
    check("good call no fatal", kpi(good, "fatal").get("fatal_triggered") is False)

    print("\n[No hallucination]")
    # Empty call: every scored KPI must be Not Done with 0 and the right reason.
    bad = [k for k in empty["kpis"]
           if k["id"] != "fatal" and (k["score"] != 0 or k["status"] != "Not Done")]
    check("empty call -> all KPIs Not Done / 0", not bad, f"violations={[b['id'] for b in bad]}")
    reasons_ok = all(
        "No transcript evidence found" in k["reason"]
        for k in empty["kpis"] if k["id"] != "fatal" and k["status"] == "Not Done"
    )
    check("empty call -> correct no-evidence reason", reasons_ok)
    check("validation flags no_hallucination", empty["validation"]["no_hallucination"] is True)

    print("\n[Scoring sanity]")
    check("good call scores higher than weak", good["total_pct"] > weak["total_pct"],
          f"good={good['total_pct']} weak={weak['total_pct']}")
    check("good call total_pct in 0..100", 0 <= good["total_pct"] <= 100)
    check("weak call review_required", weak["review_required"] is True)

    print("\n[Summary completeness]")
    sm = good["summary"]
    for field in ("executive_summary", "strengths", "missed_opportunities",
                  "coaching_suggestions", "fatal_errors", "sales_probability", "customer_intent"):
        check(f"summary has {field}", field in sm and sm[field] not in (None, ""))

    print("\n[Every KPI present + evidence-backed scoring]")
    ids = {k["id"] for k in good["kpis"]}
    expected = {k["id"] for k in SALES_KPIS}
    check("all 16 KPIs present", ids == expected, f"missing={expected - ids}")
    # Any KPI with score>0 must carry evidence (no hallucinated marks)
    no_ev = [k["id"] for k in good["kpis"]
             if k["id"] not in ("fatal",) and k["score"] > 0 and not (k["evidence"] or k["all_evidence"])]
    check("no KPI scored without evidence", not no_ev, f"offenders={no_ev}")

    print(f"\n== {PASS} passed, {FAIL} failed ==")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
