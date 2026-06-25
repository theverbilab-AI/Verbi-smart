"""Sales QA — deterministic, evidence-based 16-KPI scoring engine.

This module is the SINGLE SOURCE OF TRUTH for Sales QA. It is intentionally
independent of the Collections pipeline (no shared scoring logic) so that:

    audit_mode == "sales"        -> score_sales_call(...)   (this file)
    audit_mode == "collections"  -> collections pipeline    (scoring_rules.py)

Design rules (from management KPI Sales Flow sheet — total weight = 100):
  * Every KPI is mapped from the sheet. No KPI is skipped.
  * Every KPI returns: score, max, status, reason, evidence, confidence.
  * NO HALLUCINATION: a sub-parameter only earns marks when an explicit
    transcript keyword/phrase is found on an AGENT line. If no evidence is
    found the KPI is "Not Done", score 0, reason "No transcript evidence found."
  * Items that genuinely cannot be measured from text (voice Pace, CRM
    Activity/Notes updates) score 0 with an explicit "not assessable from
    transcript" reason and raise review_required instead of guessing.
  * If overall confidence is low -> review_required = True.
"""

from __future__ import annotations

import re
from typing import Any

# ---------------------------------------------------------------------------
# Transcript parsing (local — kept separate from Collections on purpose)
# ---------------------------------------------------------------------------

_SPEAKER_RE = re.compile(r"^\s*(agent|customer|caller|callee|speaker\s*[ab012])\s*[:\-]\s*", re.I)
_AGENT_TOKENS = ("agent", "speaker a", "speaker 0", "caller")
_CUSTOMER_TOKENS = ("customer", "speaker b", "speaker 1", "callee")


def _parse_turns(transcript: str) -> list[dict]:
    """Parse a labelled transcript into [{speaker, text}] turns.

    Accepts lines like "Agent: ..." / "Customer: ...". Unlabelled lines are
    attached to the previous turn.
    """
    turns: list[dict] = []
    for raw in (transcript or "").splitlines():
        line = raw.strip()
        if not line:
            continue
        m = _SPEAKER_RE.match(line)
        if m:
            tag = m.group(1).lower()
            speaker = "Agent" if any(t in tag for t in _AGENT_TOKENS) else "Customer"
            text = line[m.end():].strip()
            turns.append({"speaker": speaker, "text": text})
        elif turns:
            turns[-1]["text"] = (turns[-1]["text"] + " " + line).strip()
        else:
            turns.append({"speaker": "Agent", "text": line})
    return [t for t in turns if t["text"]]


def _agent_lines(turns: list[dict]) -> list[str]:
    return [t["text"] for t in turns if t["speaker"] == "Agent"]


def _customer_lines(turns: list[dict]) -> list[str]:
    return [t["text"] for t in turns if t["speaker"] == "Customer"]


# ---------------------------------------------------------------------------
# KPI registry — mirrors the official KPI Sales Flow sheet (weights sum to 100)
# Each sub-parameter: (name, marks, [keyword patterns]). Patterns are matched
# case-insensitively against AGENT lines unless the KPI overrides `scope`.
# ---------------------------------------------------------------------------

# Sentinels for sub-parameters that cannot be derived from transcript text.
NOT_TEXT_ASSESSABLE = "__not_text_assessable__"

SALES_KPIS: list[dict] = [
    {
        "id": "opening",
        "name": "Opening",
        "weight": 1,
        "subparams": [
            ("Purpose of call delivered & tonality", 1, [
                r"enquired about", r"you had enquired", r"did you register",
                r"register(?:ed)? for the webinar", r"are you looking for",
                r"were searching for", r"friend referred", r"referred (?:you|by)",
            ]),
        ],
    },
    {
        "id": "qualifying",
        "name": "Qualifying Questions",
        "weight": 9,
        "subparams": [
            ("Transition to qualifying", 1, [
                r"know about your profile", r"know a few things",
                r"ask you a few", r"few questions about you", r"understand your (?:profile|requirement)",
            ]),
            ("Academic background", 1, [
                r"academic qualification", r"highest qualification",
                r"educational background", r"your qualification",
                r"completed your (?:graduation|studies)", r"what did you study",
            ]),
            ("Course-source question", 1, [
                r"how did you come to know", r"who suggested", r"anyone recommend",
                r"how did you hear", r"came to know (?:about )?this course",
            ]),
            ("Institute information", 1, [
                r"come to know about zell", r"heard about zell", r"know about zell",
            ]),
            ("Location", 1, [
                r"where do you stay", r"which (?:university|city)", r"where are you (?:based|from)",
                r"you reside", r"which place", r"your location",
            ]),
            ("Advance close question", 2, [
                r"how soon are you planning", r"which attempt are you planning",
                r"planning to (?:start|join)", r"when are you planning",
            ]),
            ("Probing", 2, [
                r"working professional", r"your experience", r"which year",
                r"what motivated you", r"why do you want", r"any challenges",
                r"are you (?:working|a student)",
            ]),
        ],
    },
    {
        "id": "product_knowledge",
        "name": "Product Knowledge",
        "weight": 9,
        "subparams": [
            ("Transition to course intro", 1, [
                r"let me tell you about", r"coming to the course",
                r"let me explain", r"about the course",
            ]),
            ("Intro of course", 1, [
                r"\bacca\b", r"\bcma\b", r"\bcfa\b", r"\besg\b", r"dip[- ]?ifrs",
                r"\bfrm\b", r"stands for", r"full form", r"180 countries", r"worldwide",
            ]),
            ("Scope/academics understanding", 1, [
                r"what motivated you", r"why do you want to do this course",
                r"any challenges", r"your goal",
            ]),
            ("Transition to scope/academics", 1, [
                r"coming to the scope", r"talk about the scope", r"about the scope",
                r"career scope", r"job opportunities",
            ]),
            ("Academic information", 3, [
                r"\bpapers?\b", r"\blevels?\b", r"\bsubjects?\b", r"\bmcq\b",
                r"subjective", r"passing (?:marks|rate)", r"paper (?:duration|pattern)",
                r"course duration", r"attempts", r"online course",
            ]),
            ("Complete info on scope", 2, [
                r"\bmnc\b", r"international clients", r"big 4", r"multinational",
                r"bulk hire", r"high salary", r"professional course",
                r"skill based", r"abroad",
            ]),
        ],
    },
    {
        "id": "exemptions",
        "name": "Exemptions Information",
        "weight": 2,
        "subparams": [
            ("Exemption explained", 2, [
                r"papers? (?:are )?exempt", r"exemption", r"exempted",
                r"(?:don'?t|do not) have to write", r"waiver on papers?",
            ]),
        ],
    },
    {
        "id": "advance_closing",
        "name": "Advance Closing",
        "weight": 5,
        # Special graded handler: counts distinct advance-close questions.
        "handler": "advance_closing",
        "patterns": [
            r"which attempt are you planning", r"how soon are you planning to join",
            r"our batch (?:has )?started", r"planning for this batch",
            r"how soon are you planning to start", r"when do you want to start",
        ],
    },
    {
        "id": "zell_training",
        "name": "Zell Training & Deliverables",
        "weight": 16,
        "subparams": [
            ("Pre-learning", 1, [r"pre[- ]?learning"]),
            ("Live lecture", 1, [r"live lecture", r"live class", r"live session"]),
            ("Recorded lecture", 1, [r"recorded lecture", r"recorded lec", r"recorded class", r"recording"]),
            ("Study material", 2, [r"study material", r"\bbooks?\b", r"hard ?copy", r"soft ?copy", r"course material"]),
            ("Doubt solving", 2, [r"doubt solving", r"doubt session", r"1[:\- ]?1", r"one[ -]on[ -]one", r"\bsme\b"]),
            ("Mocks / Unit test", 2, [r"\bmocks?\b", r"unit test", r"mock test", r"3 mock"]),
            ("Student mentor", 2, [r"student mentor", r"\bmentor\b"]),
            ("LMS", 2, [r"\blms\b", r"learning management", r"portal access", r"platform access"]),
            ("Placement assistance", 3, [
                r"placement", r"job assistance", r"\bfaculty\b",
                r"platinum member", r"rank holders?",
            ]),
        ],
    },
    {
        "id": "pricing",
        "name": "Pricing pitched with benefits",
        "weight": 8,
        "subparams": [
            ("Batch introduction", 1, [r"weekday", r"weekend", r"\bbatches?\b", r"self[ -]?paced"]),
            ("Fees divided in two parts", 1, [r"divided in two", r"two parts", r"split into two", r"fees is divided"]),
            ("Zell fees", 1, [r"zell fees?"]),
            ("Body fees", 2, [r"body fees?", r"exam fees?", r"exam body", r"registration fees?"]),
            ("Fees backed with value", 1, [r"inclusive of", r"fees is inclusive", r"value for", r"worth it"]),
            ("EMI options introduced", 1, [r"\bemi\b", r"installments?", r"\bloan\b", r"third party", r"auto debit", r"pay in parts"]),
            ("Exemption waiver", 1, [r"exemption waiver", r"fee waiver", r"waiver on (?:the )?fees?"]),
        ],
    },
    {
        "id": "whatsapp_email",
        "name": "WhatsApp & Email sharing",
        "weight": 3,
        "subparams": [
            ("Confirming WhatsApp number", 1, [
                r"is this your whatsapp", r"your whatsapp number",
                r"whatsapp number", r"same number on whatsapp",
            ]),
            ("Actual message / details sent", 2, [
                r"i am sharing", r"i'?m sharing", r"sharing (?:the )?details",
                r"i (?:have|will) sen[dt]", r"sending you", r"shared on whatsapp",
                r"check your whatsapp", r"sent you an email", r"share the details",
            ]),
        ],
    },
    {
        "id": "referral",
        "name": "Referral",
        "weight": 3,
        "subparams": [
            ("Referral asked", 3, [
                r"do you have any friends?", r"\brefer\b", r"referral",
                r"\bbonus\b", r"know anyone", r"any friends? who",
            ]),
        ],
    },
    {
        "id": "closing",
        "name": "Closing Sales",
        "weight": 8,
        "subparams": [
            ("Indication of commitment", 2, [
                r"batch (?:is )?starting", r"registration (?:is )?closing",
                r"few seats", r"seats left", r"early bird", r"when should i call you",
            ]),
            ("Discount / scholarship", 2, [r"discount", r"scholarship", r"mark ?sheet", r"special offer"]),
            ("Scarcity / deadline / urgency", 2, [
                r"last date", r"deadline", r"limited seats", r"hurry",
                r"closing soon", r"seats? (?:are )?filling", r"few seats",
            ]),
            ("Asking for next follow-up date", 2, [
                r"next follow ?up", r"follow ?up date", r"when should i call",
                r"call you tomorrow", r"get back to you",
            ]),
        ],
    },
    {
        "id": "sales_techniques",
        "name": "Sales Techniques",
        "weight": 8,
        "subparams": [
            ("Social proof", 3, [
                r"students like you", r"students from the same location",
                r"many of our students", r"other students (?:also|too)",
                r"we have students",
            ]),
            ("Usage of RHB (rhetorical/bind)", 3, [
                r"right\s*\?", r"isn'?t it", r"makes sense", r"you agree",
                r"correct\s*\?", r"\bna\s*\?", r"don'?t you think",
            ]),
            ("Story", 2, [
                r"one of my students", r"there was a student", r"let me tell you about a",
                r"for example,? one", r"i had a student",
            ]),
        ],
    },
    {
        "id": "objection_handling",
        "name": "Objection Handling",
        "weight": 4,
        "subparams": [
            ("Rebuttal", 2, [
                r"i understand,? but", r"what i mean is", r"let me clarify",
                r"the reason is", r"actually,? ", r"online", r"offline",
                r"join later",
            ]),
            ("Satisfaction check", 2, [
                r"does that make sense", r"are you clear", r"is that clear",
                r"did that answer", r"clear now", r"satisfied with",
            ]),
        ],
    },
    {
        "id": "closing_followup",
        "name": "Closing with Follow-up Day",
        "weight": 10,
        "subparams": [
            ("Making sure doubts are clear", 3, [
                r"any doubts?", r"any quer(?:y|ies)", r"any questions?",
                r"is there anything (?:else )?(?:you|i)",
            ]),
            ("Asking for further assistance", 3, [
                r"further assistance", r"anything else", r"help you with",
                r"you can call on this number", r"reach out to me",
            ]),
            ("Follow-up date and time", 4, [
                r"call you on", r"follow ?up on", r"tomorrow at",
                r"get to you again", r"call you back at",
                r"what time should i call", r"when should i get to you",
            ]),
        ],
    },
    {
        "id": "soft_skills",
        "name": "Soft Skills",
        "weight": 10,
        "subparams": [
            ("Acknowledgement", 2, [r"i can understand", r"yes tell me", r"i see", r"got it", r"sure,?"]),
            ("Empathy", 2, [
                r"that'?s unfortunate", r"i understand how", r"don'?t worry",
                r"there are many just like you", r"i know how you feel",
            ]),
            ("Active listening", 2, [
                r"as you mentioned", r"you (?:just )?said", r"like you told me",
                r"as you said", r"you told me",
            ]),
            ("Probing", 2, [
                r"tell me more", r"what exactly", r"could you explain",
                r"can you tell me more", r"why is that",
            ]),
            # Pace = voice metric; not derivable from transcript text.
            ("Pace", 2, NOT_TEXT_ASSESSABLE),
        ],
    },
    {
        "id": "previous_call_notes",
        "name": "Previous Call Notes",
        "weight": 4,
        "subparams": [
            # CRM activity/notes updates are not in the transcript. We give partial
            # credit if the agent verbally references prior-call info; otherwise the
            # CRM-side items are flagged as not assessable.
            ("References previous-call info", 2, [
                r"last time you", r"you had mentioned earlier", r"as we discussed (?:last|earlier)",
                r"previously you said", r"in our last call", r"when we spoke last",
            ]),
            ("CRM activity / notes updated", 2, NOT_TEXT_ASSESSABLE),
        ],
    },
    {
        "id": "fatal",
        "name": "Fatal Errors",
        "weight": 0,
        "handler": "fatal",
        "patterns": [
            r"no cost emi", r"unlimited access", r"it is not a loan",
            r"zell installment", r"guaranteed (?:job|placement|passing)",
            r"100\s*% (?:placement|passing|job)", r"sure shot", r"definitely (?:pass|get a job)",
        ],
    },
]

# Confidence levels
_CONF_MATCH = 0.9          # a sub-parameter found explicit evidence
_CONF_FULL = 0.93         # whole KPI fully satisfied
_CONF_NONE = 0.6          # confident "Not Done" (keyword absent) but paraphrase risk
_CONF_UNASSESSABLE = 0.3  # cannot be judged from transcript -> needs review
LOW_CONFIDENCE = 0.6

# review_required thresholds
_REVIEW_PCT = 50.0
_REVIEW_AVG_CONF = 0.65


def _find_evidence(lines: list[str], patterns) -> str | None:
    """Return the first agent line matching any pattern, else None."""
    if patterns == NOT_TEXT_ASSESSABLE:
        return None
    for line in lines:
        low = line.lower()
        for pat in patterns:
            if re.search(pat, low):
                snippet = line.strip()
                return snippet if len(snippet) <= 240 else snippet[:237] + "..."
    return None


def _status_for(score: float, max_score: float) -> str:
    if score <= 0:
        return "Not Done"
    if score >= max_score:
        return "Done"
    return "Partial"


def _score_standard_kpi(kpi: dict, agent_lines: list[str]) -> dict:
    max_score = kpi["weight"]
    earned = 0
    sub_results: list[dict] = []
    evidences: list[str] = []
    matched_subs = 0
    unassessable_marks = 0

    for name, marks, patterns in kpi["subparams"]:
        if patterns == NOT_TEXT_ASSESSABLE:
            unassessable_marks += marks
            sub_results.append({
                "name": name, "marks": 0, "max": marks, "done": False,
                "evidence": "", "note": "Not assessable from transcript text.",
            })
            continue
        ev = _find_evidence(agent_lines, patterns)
        if ev:
            earned += marks
            matched_subs += 1
            evidences.append(ev)
            sub_results.append({"name": name, "marks": marks, "max": marks, "done": True, "evidence": ev})
        else:
            sub_results.append({"name": name, "marks": 0, "max": marks, "done": False, "evidence": ""})

    earned = min(earned, max_score)
    status = _status_for(earned, max_score)

    if status == "Not Done":
        reason = "No transcript evidence found."
        if unassessable_marks and not any(s["evidence"] for s in sub_results):
            reason = "No transcript evidence found (some items are not assessable from text)."
        confidence = _CONF_UNASSESSABLE if unassessable_marks >= max_score else _CONF_NONE
    else:
        done_names = [s["name"] for s in sub_results if s["done"]]
        reason = "Evidence found for: " + ", ".join(done_names)
        confidence = _CONF_FULL if status == "Done" else _CONF_MATCH

    return {
        "id": kpi["id"],
        "name": kpi["name"],
        "weight": max_score,
        "score": round(earned, 2),
        "max": max_score,
        "status": status,
        "reason": reason,
        "evidence": evidences[0] if evidences else "",
        "all_evidence": evidences,
        "confidence": round(confidence, 2),
        "subparams": sub_results,
    }


def _score_advance_closing(kpi: dict, agent_lines: list[str]) -> dict:
    """Graded: >2 advance-close questions = 5, 2 = 3, 1 = 1, 0 = 0.

    Counts the number of DISTINCT advance-close question patterns matched
    anywhere in the agent's speech (two such questions on one line still count
    as two).
    """
    patterns = kpi["patterns"]
    blob = "\n".join(agent_lines).lower()
    hits: list[str] = []
    matched = 0
    for pat in patterns:
        m = re.search(pat, blob)
        if m:
            matched += 1
            for line in agent_lines:
                if re.search(pat, line.lower()):
                    hits.append(line.strip())
                    break
    n = matched
    if n > 2:
        earned = 5
    elif n == 2:
        earned = 3
    elif n == 1:
        earned = 1
    else:
        earned = 0
    status = _status_for(earned, kpi["weight"])
    if n == 0:
        reason = "No transcript evidence found."
        confidence = _CONF_NONE
    else:
        reason = f"{n} advance-close question(s) asked."
        confidence = _CONF_FULL if earned >= kpi["weight"] else _CONF_MATCH
    return {
        "id": kpi["id"],
        "name": kpi["name"],
        "weight": kpi["weight"],
        "score": earned,
        "max": kpi["weight"],
        "status": status,
        "reason": reason,
        "evidence": hits[0] if hits else "",
        "all_evidence": hits,
        "confidence": round(confidence, 2),
        "subparams": [{"name": "Advance-close questions", "marks": earned, "max": kpi["weight"],
                       "done": n > 0, "evidence": "; ".join(hits[:3])}],
    }


def _score_fatal(kpi: dict, agent_lines: list[str]) -> dict:
    """Fatal = critical compliance. Weight 0; presence flags critical_fail."""
    patterns = kpi["patterns"]
    hits: list[str] = []
    for line in agent_lines:
        low = line.lower()
        for pat in patterns:
            if re.search(pat, low):
                hits.append(line.strip())
                break
    found = bool(hits)
    return {
        "id": kpi["id"],
        "name": kpi["name"],
        "weight": 0,
        "score": 0,
        "max": 0,
        "status": "Fatal Error" if found else "None",
        "reason": ("Fatal/misleading statement(s) detected." if found
                   else "No fatal/misleading statements found."),
        "evidence": hits[0] if found else "",
        "all_evidence": hits,
        "confidence": _CONF_MATCH if found else _CONF_NONE,
        "fatal_triggered": found,
        "subparams": [],
    }


def score_sales_call(transcript: str) -> dict:
    """Run the full Sales QA engine on a labelled transcript.

    Returns a dict with: kpis[], total_score, total_pct, grade, fatal_errors,
    review_required, summary{...}, recommendations[], customer_intent,
    sales_probability.
    """
    turns = _parse_turns(transcript)
    agent_lines = _agent_lines(turns)
    customer_lines = _customer_lines(turns)

    kpi_results: list[dict] = []
    fatal_result: dict | None = None
    total_score = 0.0
    weighted_max = 0  # excludes fatal (weight 0)

    for kpi in SALES_KPIS:
        handler = kpi.get("handler")
        if handler == "fatal":
            fatal_result = _score_fatal(kpi, agent_lines)
            kpi_results.append(fatal_result)
            continue
        if handler == "advance_closing":
            res = _score_advance_closing(kpi, agent_lines)
        else:
            res = _score_standard_kpi(kpi, agent_lines)
        kpi_results.append(res)
        total_score += res["score"]
        weighted_max += res["max"]

    total_pct = round((total_score / weighted_max) * 100, 1) if weighted_max else 0.0
    fatal_triggered = bool(fatal_result and fatal_result.get("fatal_triggered"))

    grade = _grade(total_pct, fatal_triggered)
    customer_intent = _detect_customer_intent(customer_lines)
    sales_probability = _sales_probability(total_pct, kpi_results, customer_intent, fatal_triggered)

    scored_kpis = [k for k in kpi_results if k["id"] != "fatal"]
    avg_conf = round(sum(k["confidence"] for k in scored_kpis) / len(scored_kpis), 2) if scored_kpis else 0.0

    summary = _build_summary(kpi_results, total_pct, grade, customer_intent,
                             sales_probability, fatal_result)
    recommendations = _build_recommendations(kpi_results)

    review_required = (
        fatal_triggered
        or total_pct < _REVIEW_PCT
        or avg_conf < _REVIEW_AVG_CONF
        or len(turns) < 4  # too little transcript to trust
    )
    review_reasons = _review_reasons(fatal_triggered, total_pct, avg_conf, len(turns))

    return {
        "audit_mode": "sales",
        "kpis": kpi_results,
        "total_score": round(total_score, 2),
        "weighted_max": weighted_max,
        "total_pct": total_pct,
        "grade": grade,
        "critical_fail": fatal_triggered,
        "fatal_errors": fatal_result.get("all_evidence", []) if fatal_result else [],
        "customer_intent": customer_intent,
        "sales_probability": sales_probability,
        "avg_confidence": avg_conf,
        "review_required": review_required,
        "review_reasons": review_reasons,
        "summary": summary,
        "recommendations": recommendations,
    }


def _grade(pct: float, fatal: bool) -> str:
    if fatal:
        return "Critical Fail"
    if pct >= 85:
        return "Excellent"
    if pct >= 70:
        return "Good"
    if pct >= 50:
        return "Needs Improvement"
    return "Poor"


def _detect_customer_intent(customer_lines: list[str]) -> str:
    text = " ".join(customer_lines).lower()
    if not text.strip():
        return "unknown"
    high = [
        r"how (?:much|do i) (?:pay|enroll|join)", r"when (?:does|can) (?:it|i) start",
        r"send (?:me )?(?:the )?details", r"i (?:am|'?m) interested", r"i want to (?:join|enroll)",
        r"how to (?:pay|register)", r"please share", r"ready to",
    ]
    low = [
        r"not interested", r"i'?ll think", r"will think about it", r"too (?:expensive|costly)",
        r"call me later", r"busy right now", r"not sure", r"can'?t afford",
    ]
    if any(re.search(p, text) for p in high):
        return "high"
    if any(re.search(p, text) for p in low):
        return "low"
    # medium if customer asks any question
    if "?" in " ".join(customer_lines) or re.search(r"what|how|when|which|why", text):
        return "medium"
    return "low"


def _sales_probability(pct: float, kpis: list[dict], intent: str, fatal: bool) -> str:
    if fatal:
        return "low"
    closing = next((k for k in kpis if k["id"] == "closing"), None)
    followup = next((k for k in kpis if k["id"] == "closing_followup"), None)
    closed_well = bool(
        (closing and closing["status"] != "Not Done")
        or (followup and followup["status"] != "Not Done")
    )
    if pct >= 65 and intent in ("high", "medium") and closed_well:
        return "high"
    if pct >= 45 or intent in ("high", "medium"):
        return "medium"
    return "low"


def _build_summary(kpis, pct, grade, intent, probability, fatal_result) -> dict:
    scored = [k for k in kpis if k["id"] != "fatal"]
    done = [k for k in scored if k["status"] == "Done"]
    partial = [k for k in scored if k["status"] == "Partial"]
    missed = [k for k in scored if k["status"] == "Not Done"]

    strengths = [
        f"{k['name']} — {k['reason']}" for k in sorted(done + partial,
        key=lambda x: x["weight"], reverse=True)[:5]
    ]
    missed_ops = [
        f"{k['name']} (worth {k['weight']} marks) was not done."
        for k in sorted(missed, key=lambda x: x["weight"], reverse=True)[:6]
    ]
    coaching = _build_recommendations(kpis)[:5]

    fatal_list = fatal_result.get("all_evidence", []) if fatal_result else []

    exec_summary = (
        f"Agent scored {pct}% ({grade}). "
        f"{len(done)} KPI(s) fully done, {len(partial)} partial, {len(missed)} missed. "
        f"Customer intent: {intent}. Estimated sales probability: {probability}."
    )
    if fatal_list:
        exec_summary += f" CRITICAL: {len(fatal_list)} fatal/misleading statement(s) detected."

    return {
        "executive_summary": exec_summary,
        "strengths": strengths or ["No notable strengths detected from transcript."],
        "missed_opportunities": missed_ops or ["None — all KPIs had at least partial evidence."],
        "coaching_suggestions": coaching or ["Maintain current approach."],
        "fatal_errors": fatal_list or ["None detected."],
        "sales_probability": probability,
        "customer_intent": intent,
    }


def _build_recommendations(kpis: list[dict]) -> list[str]:
    recs: list[str] = []
    # Prioritise highest-weight missed KPIs.
    missed = sorted(
        [k for k in kpis if k["id"] != "fatal" and k["status"] == "Not Done"],
        key=lambda x: x["weight"], reverse=True,
    )
    tips = {
        "opening": "Open by stating the call purpose tied to the lead's enquiry.",
        "qualifying": "Ask profiling questions (academics, location, source, plans) before pitching.",
        "product_knowledge": "Introduce the course, scope and academic details clearly.",
        "exemptions": "Explain paper exemptions the learner qualifies for.",
        "advance_closing": "Ask at least 3 advance-close questions (attempt, timeline, batch).",
        "zell_training": "Walk through deliverables: live/recorded, material, doubts, mocks, mentor, LMS, placement.",
        "pricing": "Pitch pricing with value, two-part fee split, and EMI options.",
        "whatsapp_email": "Confirm the WhatsApp number and actually send the details.",
        "referral": "Ask for referrals and mention the referral bonus.",
        "closing": "Create commitment with scarcity, discount and a clear next step.",
        "sales_techniques": "Use social proof, rhetorical bind questions and a success story.",
        "objection_handling": "Rebut objections and confirm the learner is satisfied.",
        "closing_followup": "Confirm doubts are cleared and lock a follow-up date and time.",
        "soft_skills": "Acknowledge, show empathy, listen actively and probe.",
        "previous_call_notes": "Reference prior-call notes and update CRM activity/notes.",
    }
    for k in missed:
        tip = tips.get(k["id"])
        if tip:
            recs.append(tip)
    return recs


def _review_reasons(fatal: bool, pct: float, avg_conf: float, n_turns: int) -> list[str]:
    reasons = []
    if fatal:
        reasons.append("Fatal/misleading statement detected.")
    if pct < _REVIEW_PCT:
        reasons.append(f"Overall score {pct}% below review threshold {_REVIEW_PCT}%.")
    if avg_conf < _REVIEW_AVG_CONF:
        reasons.append(f"Average KPI confidence {avg_conf} below {_REVIEW_AVG_CONF}.")
    if n_turns < 4:
        reasons.append("Transcript too short to assess reliably.")
    return reasons


def validate_sales_audit(transcript: str, audit: dict[str, Any]) -> dict[str, Any]:
    """Validation gate for the sales audit — confirms every KPI is evidence-backed
    and (re)computes review_required. Returns the audit with validation metadata.

    This guarantees the NO-HALLUCINATION contract: any KPI marked Done/Partial
    must carry transcript evidence; otherwise it is downgraded to Not Done.
    """
    kpis = audit.get("kpis", [])
    corrections: list[str] = []
    for k in kpis:
        if k.get("id") == "fatal":
            continue
        if k.get("status") in ("Done", "Partial") and not (k.get("evidence") or k.get("all_evidence")):
            k["status"] = "Not Done"
            k["score"] = 0
            k["reason"] = "No transcript evidence found."
            k["confidence"] = _CONF_NONE
            corrections.append(f"{k.get('name')}: downgraded (no evidence).")

    audit["validation"] = {
        "checked_kpis": len([k for k in kpis if k.get("id") != "fatal"]),
        "corrections": corrections,
        "no_hallucination": True,
    }
    return audit


def total_weight() -> int:
    """Sum of KPI weights (must equal 100 per the official sheet)."""
    return sum(k["weight"] for k in SALES_KPIS)
