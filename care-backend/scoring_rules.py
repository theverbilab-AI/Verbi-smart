"""
CARE rule-based scoring calibration — parameter-by-parameter.

Rule-based scoring A1–A9 per Verbicare Changes doc + RPC/non-collections guardrails.
"""

from __future__ import annotations

import re
from typing import Any


def _lines_by_speaker(transcript: str) -> tuple[list[str], list[str]]:
    agent, customer = [], []
    for raw in (transcript or "").splitlines():
        line = raw.strip()
        if not line:
            continue
        m = re.match(r"^(agent|customer)\s*:\s*(.*)$", line, re.I)
        if not m:
            continue
        if m.group(1).lower() == "agent":
            agent.append(m.group(2).strip())
        else:
            customer.append(m.group(2).strip())
    return agent, customer


def _transcript_turns(transcript: str) -> list[tuple[str, str]]:
    turns: list[tuple[str, str]] = []
    for raw in (transcript or "").splitlines():
        m = re.match(r"^(agent|customer)\s*:\s*(.*)$", raw.strip(), re.I)
        if m:
            who = "Agent" if m.group(1).lower() == "agent" else "Customer"
            turns.append((who, (m.group(2) or "").strip()))
    return turns


def _evaluate_rpc_status(
    turns: list[tuple[str, str]], wrong_number_cues: tuple[str, ...]
) -> tuple[bool, bool, bool]:
    """
    RPC = right party contact. Counts agent intro + customer engagement (e.g. "Yes, tell me"),
    not only explicit "Am I speaking with Mr X?" questions.
    """
    rpc_question_cues = (
        "am i speaking", "is this", "speaking with", "confirm your name",
        "may i speak", "are you mr", "are you ms", "are you mrs", "your good name",
        "naam confirm", "aap hi", "kya main", "right party", "borrower",
        "customer name", "who am i speaking",
    )
    rpc_intro_cues = (
        "this is", "my name is", "i am speaking", "speaking on behalf",
        "calling from", "on behalf of", "good morning", "good afternoon",
    )
    rpc_confirm_customer = (
        "yes", "haan", "ji", "speaking", "this is", "main hoon", "bol raha",
        "bol rahi", "correct", "right", "myself", "that's me", "same person",
        "haan bol", "haan ji", "main hi", "yahi hoon", "yahi hun", "sahi number",
        "correct number", "who is speaking", "i am the", "mera naam", "tell me",
    )
    loan_cues = (
        "outstanding", "overdue", "emi", "loan amount", "pending amount",
        "due is", "balance is", "your payment", "payment for", "payment is pending",
        "haven't made the payment", "not paid", "clear the",
    )

    rpc_attempted = False
    rpc_confirmed = False
    loan_before_rpc = False
    customer_engaged = False

    for idx, (speaker, text) in enumerate(turns):
        low = text.lower()
        if speaker == "Agent":
            if any(c in low for c in rpc_question_cues):
                rpc_attempted = True
            if any(c in low for c in rpc_intro_cues) or re.search(
                r"\bthis is\s+[a-z][a-z'-]{1,}\s+speaking\b", low
            ):
                rpc_attempted = True
            if (
                not rpc_confirmed
                and not customer_engaged
                and any(c in low for c in loan_cues)
            ):
                loan_before_rpc = True
        else:
            short_ack = len(low) < 100 and not any(w in low for w in wrong_number_cues)
            ready = bool(
                re.search(r"^(yes|haan|ji|okay|ok)\b", low)
                or re.search(r"\b(tell me|boliye|bolo|go ahead)\b", low)
            )
            if re.search(r"\b(yes|haan|ji)\s+speaking\b", low):
                customer_engaged = True
                rpc_confirmed = True
            if short_ack and (
                ready
                or any(c in low for c in rpc_confirm_customer)
            ):
                customer_engaged = True
                prior_agent_intro = any(
                    t[0] == "Agent"
                    and (
                        any(c in t[1].lower() for c in rpc_intro_cues)
                        or re.search(r"\bthis is\s+\w+", t[1].lower())
                    )
                    for t in turns[:idx]
                )
                if rpc_attempted or prior_agent_intro:
                    rpc_confirmed = True

    if len(turns) >= 2 and turns[0][0] == "Agent" and turns[1][0] == "Customer":
        a0 = turns[0][1].lower()
        c0 = turns[1][1].lower()
        agent_opened = (
            any(c in a0 for c in rpc_intro_cues)
            or re.search(r"\bthis is\s+[a-z][a-z'-]{1,}\s+speaking\b", a0)
            or ("speaking" in a0 and "this is" in a0)
        )
        customer_ready = (
            re.search(r"^(yes|haan|ji|okay|ok)[,.]?\s*(tell me|sir|madam|ma'am)?\s*$", c0)
            or (re.search(r"^(yes|haan|ji)\b", c0) and "tell" in c0)
            or re.search(r"^(yes|haan|ji)\s+speaking\b", c0)
            or c0.strip() in {"tell me", "yes", "haan", "ji", "yes tell me", "yes speaking"}
        )
        if agent_opened and customer_ready and not any(w in c0 for w in wrong_number_cues):
            rpc_attempted = True
            rpc_confirmed = True
            loan_before_rpc = False

    if rpc_confirmed:
        loan_before_rpc = False

    agent_text = " ".join(t[1] for t in turns if t[0] == "Agent").lower()
    if any(c in agent_text for c in ("thank you mr", "thank you ms", "thank you shri", "dear mr", "dear ms")):
        rpc_confirmed = True
        rpc_attempted = True

    return rpc_attempted, rpc_confirmed, loan_before_rpc


_LENDER_FILENAME_MARKERS = (
    "tala", "okcredit", "ok-credit", "ok_credit", "kreditbee", "moneyview",
    "branch", "cashe", "navi", "paytm", "lending", "collections",
)


def _filename_implies_collections(filename_hint: str) -> bool:
    """Uploaded collections files often lack loan keywords in a short STT transcript."""
    name = (filename_hint or "").lower()
    if not name:
        return False
    if any(m in name for m in _LENDER_FILENAME_MARKERS):
        return True
    if re.search(r"\d{5,}[-_][a-z][a-z0-9_-]*[-_](tala|credit|loan|emi)", name, re.I):
        return True
    if re.search(r"\d{5,}[-_][a-z]{2,}[-_][a-z]{2,}", name, re.I):
        return True
    return bool(re.search(r"\b\d{6,}\b", name) and re.search(r"[-_][a-z]{2,}", name, re.I))


def detect_call_context(transcript: str, filename_hint: str = "") -> dict[str, Any]:
    """Detect RPC, collections vs non-collections, and early disclosure."""
    agent_lines, customer_lines = _lines_by_speaker(transcript)
    agent_text = " ".join(agent_lines).lower()
    customer_text = " ".join(customer_lines).lower()
    full_lower = (transcript or "").lower()
    file_lower = (filename_hint or "").lower()

    collections_cues = (
        "loan", "emi", "outstanding", "overdue", "payment", "due amount", "pending",
        "ok credit", "tala", "collection", "borrower", "installment", "settlement",
        "cibil", "legal notice", "days past", "dpd", "rupees", "rs ", "₹",
        "noc", "default", "recovery", "pay today", "pay tomorrow",
    )
    collections_behavior = (
        "pick up the phone", "won't take much time", "wont take much time",
        "we will take two minutes", "talk for a while", "better if you talk",
        "please talk", "when will you pay", "payment due", "calling regarding",
        "regarding your loan", "regarding your emi", "baad mein phone",
    )
    non_collection_cues = (
        "wrong number", "delivery", "courier", "insurance claim", "doctor appointment",
        "hospital appointment", "customer care", "tech support", "survey", "feedback call",
        "not a loan", "no loan", "who are you calling", "marketing call", "sales pitch",
    )
    is_collections = (
        any(c in full_lower for c in collections_cues)
        or any(c in agent_text for c in collections_behavior)
        or _filename_implies_collections(filename_hint)
        or any(c in file_lower for c in collections_cues)
    )
    if any(c in full_lower for c in non_collection_cues) and not any(
        c in full_lower for c in ("emi", "outstanding", "overdue", "loan amount", "dpd", "borrower")
    ):
        if not _filename_implies_collections(filename_hint):
            is_collections = False

    wrong_number_cues = (
        "wrong number", "galat number", "not this person", "not him", "not her",
        "number change", "changed my number", "who is this", "don't know him",
        "don't know her", "no such person", "not available", "passed away",
        "deceased", "wrong party",
    )
    is_wrong_number = any(c in full_lower for c in wrong_number_cues)

    turns = _transcript_turns(transcript)
    rpc_attempted, rpc_confirmed, loan_before_rpc = _evaluate_rpc_status(
        turns, wrong_number_cues
    )
    if is_wrong_number:
        rpc_confirmed = False
        loan_before_rpc = False
    elif is_collections and not rpc_confirmed:
        loan_before_rpc = loan_before_rpc or (
            any(
                c in agent_text
                for c in (
                    "outstanding", "overdue", "emi", "loan amount", "pending amount",
                    "your payment", "payment for", "payment is pending",
                )
            )
            and not rpc_attempted
        )

    return {
        "is_collections": is_collections,
        "is_wrong_number": is_wrong_number,
        "rpc_attempted": rpc_attempted,
        "rpc_confirmed": rpc_confirmed,
        "loan_before_rpc": loan_before_rpc,
        "agent_text": agent_text,
        "customer_text": customer_text,
        "full_lower": full_lower,
    }


_HONORIFIC_STOPWORDS = {
    "yes", "no", "ok", "okay", "okk", "okey", "thank", "thanks", "hello", "hi",
    "yeah", "haan", "haa", "haanji", "ji", "jee", "good", "actually", "sorry",
    "right", "thik", "achha", "achcha", "tell", "please", "kya", "are", "is",
    "i", "you", "we", "he", "she", "it", "they", "this", "that", "and", "but",
    "or", "so", "if", "the", "a", "an", "to", "for", "of", "with", "from",
    "main", "aap", "mein", "tum", "hain", "hai", "ho", "kar", "kya", "se",
    "mr", "ms", "mrs", "shri", "smt", "miss", "dear", "speaking", "calling",
}


_NAME_PRECEDING_VERBS = {
    "speaking", "talking", "calling", "addressing", "contacting",
    "is", "this", "are", "you", "with", "to", "for", "from",
}


def _looks_like_a_name(word: str) -> bool:
    """A name word: 3+ letters, not a stopword/verb, not a digit string."""
    word = (word or "").strip().lower()
    if len(word) < 3 or not word.isalpha():
        return False
    if word in _HONORIFIC_STOPWORDS or word in _NAME_PRECEDING_VERBS:
        return False
    return True


def _customer_name_mentioned(agent_text: str) -> bool:
    """
    Detect if the agent addressed the customer by name.
    Catches Mr/Dear (Western), Indian honorifics (sir/ji/sahab), and verb-prefix
    patterns (`speaking with X`, `is this X`, `am I talking to X`, `Hello X sir`).
    """
    if not agent_text:
        return False
    text = agent_text.lower()

    if re.search(r"\b(mr|ms|mrs|shri|smt|miss|dear)\s+[a-z][a-z'-]{1,}", text):
        return True

    verb_prefix = re.compile(
        r"\b(?:speaking|talking|calling)\s+(?:with|to)\s+([a-z][a-z'-]{2,})",
        re.I,
    )
    for m in verb_prefix.finditer(text):
        if _looks_like_a_name(m.group(1)):
            return True

    is_this_prefix = re.compile(
        r"\b(?:is\s+this|are\s+you|am\s+i\s+(?:speaking|talking)\s+(?:with|to))\s+([a-z][a-z'-]{2,})",
        re.I,
    )
    for m in is_this_prefix.finditer(text):
        if _looks_like_a_name(m.group(1)):
            return True

    hello_prefix = re.compile(
        r"\b(?:hello|hi|namaste|good\s+(?:morning|afternoon|evening))[\s,]+([a-z][a-z'-]{2,})\s+(?:sir|madam|ji)",
        re.I,
    )
    for m in hello_prefix.finditer(text):
        if _looks_like_a_name(m.group(1)):
            return True

    honorific_pattern = re.compile(
        r"\b([a-z][a-z'-]{2,})\s+(?:sir|sahab|sahib|madam|ma'am|maam|ji|jee|bhai|behen|garu|anna|akka)\b",
        re.I,
    )
    for m in honorific_pattern.finditer(text):
        if _looks_like_a_name(m.group(1)):
            return True

    return False


_RPC_DENY_CUSTOMER = (
    "wrong number", "galat number", "not this person", "not him", "not her",
    "who are you", "who is this", "he is not here", "she is not here",
    "not available", "passed away", "deceased", "wrong party", "don't know him",
    "don't know her", "no such person",
)

_DISCLAIMER_PHRASES = (
    "recorded", "monitored", "quality purpose", "training purpose", "this call is",
    "call may be recorded", "call is being recorded", "for quality and training",
    "disclaimer", "recorded line", "quality assurance",
    "purpose of this call", "regarding your loan", "regarding your emi",
    "payment reminder", "overdue payment", "collections call",
)

_AGENT_INTRO_PHRASES = (
    "this is", "my name is", "i am speaking", "speaking on behalf", "calling from",
    "on behalf of", "from tala", "from ok credit", "from the bank", "from bank",
    "collections department", "recovery team",
)

_THIRD_PARTY_CUES = (
    "mother", "father", "wife", "husband", "brother", "sister", "son", "daughter",
    "friend", "relative", "my brother", "my sister", "he is not here", "she is not here",
    "not him", "not her", "third party",
)

_LOAN_DISCLOSURE_CUES = (
    "outstanding", "overdue", "emi", "loan amount", "loan payment", "payment is pending",
    "your payment", "due amount", "balance", "legal notice", "cibil",
)


def detect_call_kpis(
    transcript: str,
    agent_transcript: str | None = None,
    customer_transcript: str | None = None,
    filename_hint: str = "",
) -> dict[str, Any]:
    """
    Deterministic KPI / compliance signals for hybrid scoring.
    Used before saving scores to DB and to correct LLM mistakes.
    """
    transcript = (transcript or "").strip()
    ctx = detect_call_context(transcript, filename_hint)
    agent_lines, customer_lines = _lines_by_speaker(transcript)
    if agent_transcript:
        agent_lines = [ln.strip() for ln in agent_transcript.splitlines() if ln.strip()]
    if customer_transcript:
        customer_lines = [ln.strip() for ln in customer_transcript.splitlines() if ln.strip()]

    agent_text = ctx["agent_text"] or " ".join(agent_lines).lower()
    customer_text = ctx["customer_text"] or " ".join(customer_lines).lower()
    full_lower = ctx["full_lower"]

    rpc_confirmed = bool(ctx.get("rpc_confirmed"))
    rpc_denied = any(p in customer_text or p in full_lower for p in _RPC_DENY_CUSTOMER)
    if rpc_denied:
        rpc_confirmed = False

    if not rpc_confirmed:
        for cl in customer_lines[:8]:
            low = cl.lower()
            if any(p in low for p in _RPC_DENY_CUSTOMER):
                continue
            if re.search(r"\bthis is\s+[a-z][a-z'-]{2,}\b", low):
                rpc_confirmed = True
                break
            if re.search(r"\b(yes|haan|ji)\s+speaking\b", low):
                rpc_confirmed = True
                break

    agent_intro = bool(
        re.search(r"\bthis is\s+[a-z][a-z'-]{1,}\s+speaking\b", agent_text)
        or any(p in agent_text for p in _AGENT_INTRO_PHRASES)
    )

    disclaimer_given = bool(
        any(p in agent_text for p in _DISCLAIMER_PHRASES)
        and not (
            agent_text.strip().startswith("hello")
            and not any(p in agent_text for p in ("recorded", "loan", "emi", "payment", "overdue", "purpose"))
        )
    )

    customer_name_confirmed = bool(
        _customer_name_mentioned(agent_text)
        or re.search(r"\b(am i speaking with|may i speak with|is this)\s+[a-z]", agent_text)
        or any(re.search(r"\bthis is\s+[a-z][a-z'-]{2,}\b", cl.lower()) for cl in customer_lines)
    )

    ptp = _extract_ptp_details(transcript, ctx)
    third = _detect_third_party_compliance(agent_text, customer_text, full_lower)
    dispositions = _detect_dispositions(transcript, ctx, ptp, third)

    risk_flags: list[str] = []
    compliance_flags: list[str] = []
    ai_detection: list[str] = []

    if ptp["ptp_detected"]:
        compliance_flags.append("PTP_DETECTED")
        ai_detection.append("PTP_DETECTED")
    if third["third_party"]:
        ai_detection.append("THIRD_PARTY")
        if third["compliance_violation"]:
            compliance_flags.extend(["WRONG_DISCLOSURE", "THIRD_PARTY_BREACH"])
            risk_flags.append("THIRD_PARTY_BREACH")
            ai_detection.append("THIRD_PARTY_BREACH")
        else:
            compliance_flags.append("THIRD_PARTY_SAFE")
            ai_detection.append("THIRD_PARTY_SAFE")

    if ctx.get("is_collections") and not rpc_confirmed and not rpc_denied:
        if any(p in agent_text for p in _LOAN_DISCLOSURE_CUES) and ctx.get("loan_before_rpc"):
            compliance_flags.append("RPC_MISSED")
            ai_detection.append("RPC_MISSED")
    elif rpc_confirmed:
        compliance_flags = [f for f in compliance_flags if f != "RPC_MISSED"]
        ai_detection = [d for d in ai_detection if d != "RPC_MISSED"]

    critical_fail = 0
    critical_reason = ""
    if third["compliance_violation"]:
        critical_fail = 1
        critical_reason = "Loan/payment details disclosed to third party"
    elif any(p in full_lower for p in ("idiot", "stupid", "threaten", "bloody", "shut up")):
        critical_fail = 1
        critical_reason = "Abusive or threatening language"

    confidence = 72
    if rpc_confirmed:
        confidence += 8
    if agent_intro:
        confidence += 5
    if ptp["ptp_detected"]:
        confidence += min(ptp.get("ptp_confidence", 0) // 5, 10)
    confidence = min(95, confidence)

    ai_suggestion = _kpi_coaching_suggestion(
        rpc_confirmed, agent_intro, disclaimer_given, customer_name_confirmed, third, ptp
    )

    return {
        "rpc_confirmed": rpc_confirmed,
        "rpc_attempted": bool(ctx.get("rpc_attempted") or agent_intro),
        "agent_intro": agent_intro,
        "customer_name_confirmed": customer_name_confirmed,
        "disclaimer_given": disclaimer_given,
        "ptp_detected": 1 if ptp["ptp_detected"] else 0,
        "ptp_date": ptp.get("ptp_date") or "",
        "ptp_amount": ptp.get("ptp_amount") or "",
        "ptp_mode": ptp.get("ptp_mode") or "",
        "ptp_confidence": ptp.get("ptp_confidence", 0),
        "dispositions": dispositions,
        "third_party": third["third_party"],
        "compliance_violation": third["compliance_violation"],
        "risk_flags": risk_flags,
        "compliance_flags": compliance_flags,
        "critical_fail": critical_fail,
        "critical_reason": critical_reason,
        "ai_detection": ai_detection or ["NONE"],
        "ai_suggestion": ai_suggestion,
        "confidence": confidence,
        "is_collections": bool(ctx.get("is_collections")),
        "is_wrong_number": bool(ctx.get("is_wrong_number")),
        "_ctx": ctx,
    }


def _extract_ptp_details(transcript: str, ctx: dict[str, Any]) -> dict[str, Any]:
    full_lower = ctx["full_lower"]
    customer_text = ctx["customer_text"]
    agent_text = ctx["agent_text"]

    pay_cues = (
        "i will pay", "will pay", "i can pay", "pay tomorrow", "pay today", "pay on",
        "pay by", "promise to pay", "commit to pay", "i will do it", "kar dunga",
        "kar dungi", "bhar dunga", "arrange", "will arrange", "after salary",
        "next week", "by evening", "payment on",
    )
    detected = any(p in full_lower for p in pay_cues)
    if re.search(r"\bwill do it in\b.*\b(week|month|day)", full_lower):
        detected = True
    if re.search(r"\b\d+\s*to\s*\d+\s*weeks?\b", full_lower):
        detected = True

    amount = ""
    m_amt = re.search(
        r"\b(?:rs\.?|inr|₹)\s*(\d[\d,]*)\b|\b(\d{3,7})\s*(?:rupees|rs)\b|\bi can pay\s+(\d[\d,]*)",
        full_lower,
    )
    if m_amt:
        amount = next((g.replace(",", "") for g in m_amt.groups() if g), "")

    date = ""
    for phrase, label in (
        ("tomorrow", "tomorrow"),
        ("today", "today"),
        ("next week", "next week"),
        ("after salary", "after salary"),
        ("by evening", "by evening"),
        ("monday", "monday"),
        ("tuesday", "tuesday"),
    ):
        if phrase in customer_text or phrase in full_lower:
            date = label
            break
    m_weeks = re.search(r"\b(\d+)\s*to\s*(\d+)\s*weeks?\b", full_lower)
    if m_weeks:
        date = f"{m_weeks.group(1)}-{m_weeks.group(2)} weeks"
    m_days = re.search(r"\bin\s+(\d+)\s+days?\b", full_lower)
    if m_days:
        date = f"{m_days.group(1)} days"

    mode = ""
    for m in ("upi", "cash", "neft", "imps", "online", "app", "link", "branch"):
        if m in full_lower:
            mode = m.upper() if m in ("upi", "neft", "imps") else m
            break

    confidence = 0
    if detected:
        confidence = 55
        if amount:
            confidence += 15
        if date:
            confidence += 15
        if mode:
            confidence += 10
        if any(p in agent_text for p in ("confirm", "noted", "recorded")):
            confidence += 5

    return {
        "ptp_detected": bool(detected),
        "ptp_amount": amount,
        "ptp_date": date,
        "ptp_mode": mode,
        "ptp_confidence": min(100, confidence),
    }


def _detect_third_party_compliance(
    agent_text: str, customer_text: str, full_lower: str
) -> dict[str, bool]:
    third_party = any(p in customer_text or p in full_lower for p in _THIRD_PARTY_CUES)
    violation = False
    if third_party:
        violation = any(p in agent_text for p in _LOAN_DISCLOSURE_CUES)
    return {"third_party": third_party, "compliance_violation": violation}


def _detect_dispositions(
    transcript: str,
    ctx: dict[str, Any],
    ptp: dict[str, Any],
    third: dict[str, bool],
) -> list[str]:
    full_lower = ctx["full_lower"]
    tags: list[str] = []

    def add(tag: str):
        if tag not in tags:
            tags.append(tag)

    if ptp.get("ptp_detected"):
        add("PTP")
    if any(p in full_lower for p in ("call later", "callback", "call back", "call you back")):
        add("CALLBACK")
    if any(p in full_lower for p in ("disconnected", "call got disconnected", "line cut")):
        add("DISCONNECTED")
    if any(p in full_lower for p in ("lost my job", "no job", "financial problem", "hardship", "no money")):
        add("FINANCIAL_HARDSHIP")
    if any(p in full_lower for p in ("hospital", "medical", "surgery", "doctor", "admitted")):
        add("MEDICAL_ISSUE")
    if any(p in full_lower for p in ("don't understand", "hindi nahi", "english nahi", "language")):
        add("LANGUAGE_ISSUE")
    if any(p in full_lower for p in ("app not", "link not", "upi fail", "not working", "payment app")):
        add("APP_ISSUE")
    if third.get("third_party"):
        add("THIRD_PARTY")
    if any(p in full_lower for p in ("won't pay", "will not pay", "refuse", "not paying")):
        add("REFUSED_TO_PAY")
    if any(p in full_lower for p in ("settlement", "one time settlement", "ots")):
        add("SETTLEMENT_REQUEST")
    if any(p in full_lower for p in ("legal notice", "court", "lawyer", "police")):
        add("LEGAL_ESCALATION")
    if ctx.get("is_wrong_number"):
        add("WRONG_NUMBER")
    if not tags:
        add("OTHER")
    return tags


def _kpi_coaching_suggestion(
    rpc: bool,
    intro: bool,
    disclaimer: bool,
    name: bool,
    third: dict[str, bool],
    ptp: dict[str, Any],
) -> str:
    tips: list[str] = []
    if not disclaimer:
        tips.append("Give recording disclaimer and call purpose before loan discussion.")
    if not intro:
        tips.append("State agent name and company/app clearly.")
    if not rpc:
        tips.append("Confirm borrower identity (RPC) before sharing loan or payment details.")
    elif not name:
        tips.append("Use customer name after RPC confirmation.")
    if third.get("third_party") and third.get("compliance_violation"):
        tips.append("Never disclose loan/dues to a third party — ask them to have the borrower call back.")
    if ptp.get("ptp_detected") and not ptp.get("ptp_amount"):
        tips.append("Capture PTP amount, date, and payment mode explicitly.")
    return " ".join(tips) if tips else "Call handling aligns with collections QA expectations."


def kpis_to_opening_audit(kpis: dict[str, Any]) -> dict[str, bool]:
    """Map KPI dict to opening_audit shape consumed by the dashboard."""
    return {
        "disclaimer_given": bool(kpis.get("disclaimer_given")),
        "agent_intro_done": bool(kpis.get("agent_intro")),
        "customer_name_used": bool(kpis.get("customer_name_confirmed")),
        "rpc_confirmed": bool(kpis.get("rpc_confirmed")),
        "rpc_attempted": bool(kpis.get("rpc_attempted")),
        "is_collections": bool(kpis.get("is_collections")),
    }


def merge_kpis_into_scoring_result(result: dict, kpis: dict[str, Any]) -> dict:
    """Overlay deterministic KPIs onto LLM scoring output before DB save."""
    ctx = kpis.get("_ctx") or {}
    ctx["rpc_confirmed"] = bool(kpis.get("rpc_confirmed"))
    ctx["rpc_attempted"] = bool(kpis.get("rpc_attempted"))
    kpis["_ctx"] = ctx

    opening = kpis_to_opening_audit(kpis)
    result["opening_audit"] = opening

    result["ptp_detected"] = bool(kpis.get("ptp_detected"))
    if kpis.get("ptp_amount"):
        result["ptp_amount"] = kpis["ptp_amount"]
    if kpis.get("ptp_date"):
        result["ptp_date"] = kpis["ptp_date"]
    if kpis.get("ptp_mode"):
        result["ptp_mode"] = kpis["ptp_mode"]

    dispositions = list(kpis.get("dispositions") or [])
    if dispositions:
        result["disposition"] = dispositions[0]
        result["dispositions"] = dispositions

    llm_flags = {str(f).upper() for f in _as_list(result.get("compliance_flags")) if f}
    kpi_flags = {str(f).upper() for f in (kpis.get("compliance_flags") or []) if f}
    merged_flags = fix_rpc_compliance_flags(list(llm_flags | kpi_flags), ctx)
    result["compliance_flags"] = merged_flags

    det = list(_as_list(result.get("ai_detection")))
    for d in kpis.get("ai_detection") or []:
        if d and d not in det:
            det.append(d)
    if opening.get("rpc_confirmed"):
        det = [
            x for x in det
            if "RPC_MISSED" not in str(x).upper() and "RPC NOT CONFIRMED" not in str(x).upper()
        ]
        if not kpis.get("compliance_violation"):
            det = [x for x in det if "WRONG_DISCLOSURE" not in str(x).upper()]
    result["ai_detection"] = det or ["NONE"]

    if kpis.get("ai_suggestion"):
        result["ai_suggestion"] = kpis["ai_suggestion"]
    result["confidence"] = max(int(result.get("confidence") or 0), int(kpis.get("confidence") or 0))

    if kpis.get("critical_fail"):
        result["critical_fail"] = True
        result["critical_reason"] = kpis.get("critical_reason") or result.get("critical_reason") or ""

    result["risk_flags"] = list(dict.fromkeys(
        _as_list(result.get("risk_flags")) + list(kpis.get("risk_flags") or [])
    ))

    if ctx.get("is_collections") and not kpis.get("critical_fail") and not ctx.get("is_wrong_number"):
        scores = dict(result.get("scores") or {})
        if opening.get("rpc_confirmed") and opening.get("agent_intro_done"):
            scores["A1_opening"] = max(scores.get("A1_opening", 0), 1)
        if kpis.get("ptp_detected"):
            scores["A5_commitment_ptp"] = max(scores.get("A5_commitment_ptp", 0), 1)
        result["scores"] = scores

    if kpis.get("third_party") and not kpis.get("compliance_violation"):
        scores = dict(result.get("scores") or {})
        for key, minimum in (
            ("A1_opening", 1), ("A3_probing", 1), ("A4_negotiation", 1),
            ("A6_closing", 1), ("A7_professionalism", 2), ("A8_call_handling", 1),
        ):
            scores[key] = max(scores.get(key, 0), minimum)
        result["scores"] = scores
        result["critical_fail"] = False
        result["total_score"] = sum(scores.values())
        result["total_score_pct"] = int(round((result["total_score"] / 20) * 100))

    return result


def audit_opening_elements(transcript: str, ctx: dict[str, Any] | None = None) -> dict[str, bool]:
    """Opening checklist per Verbicare doc (disclaimer, intro, name, RPC)."""
    kpis = detect_call_kpis(transcript)
    if ctx:
        kpis["_ctx"] = ctx
    opening = kpis_to_opening_audit(kpis)
    print(
        f"[OPENING_AUDIT] rpc={opening['rpc_confirmed']} intro={opening['agent_intro_done']} "
        f"name={opening['customer_name_used']} disclaimer={opening['disclaimer_given']}",
        flush=True,
    )
    return opening


def apply_sequential_parameter_gating(scores: dict[str, int], ctx: dict[str, Any]) -> dict[str, int]:
    """
    Verbicare: do not score Case Knowledge+ until Opening is closed.
    If A1 is 0 on a collections call, later parameters stay 0.
    """
    if not ctx.get("is_collections") or ctx.get("is_wrong_number"):
        return scores
    if scores.get("A1_opening", 0) > 0:
        return scores
    gated = dict(scores)
    for key in (
        "A2_case_knowledge", "A3_probing", "A4_negotiation",
        "A5_commitment_ptp", "A6_closing",
    ):
        gated[key] = 0
    return gated


def score_a1_opening(transcript: str, ctx: dict[str, Any] | None = None) -> int:
    """
    A.1 Opening (0–2) per Verbicare doc:
    2 = disclaimer + customer name + intro + RPC confirmed (order acceptable with minor gaps)
    1 = most elements present, one missing or weak
    0 = missing disclosure / identity not confirmed on collections calls
    """
    ctx = ctx or detect_call_context(transcript)
    agent_text = ctx["agent_text"]

    has_disclaimer = any(
        p in agent_text
        for p in (
            "recorded", "monitored", "quality purpose", "training", "this call is",
            "call may be recorded", "for quality", "disclaimer",
        )
    )
    has_intro = any(
        p in agent_text
        for p in (
            "speaking on behalf", "calling from", "this is", "my name is", "i am ",
            "on behalf of", "from ok credit", "from tala", "from the bank",
        )
    )
    has_customer_name = bool(
        re.search(r"\b(mr|ms|mrs|shri|smt)\s+\w+", agent_text)
        or re.search(r"dear\s+\w+", agent_text)
        or ("your name" in agent_text and ctx.get("rpc_confirmed"))
    )
    rpc_ok = bool(ctx.get("rpc_confirmed"))

    if not ctx.get("is_collections"):
        if has_intro or "hello" in agent_text:
            return 1
        return 0

    elements = [has_disclaimer, has_intro, has_customer_name or rpc_ok, rpc_ok]
    present = sum(1 for x in elements if x)
    if present >= 4 or (has_disclaimer and has_intro and rpc_ok):
        return 2
    if present >= 2 or (has_intro and rpc_ok):
        return 1
    if has_intro or ("hello" in agent_text and rpc_ok):
        return 1
    return 0


def score_a2_case_knowledge(transcript: str, ctx: dict[str, Any] | None = None) -> int:
    """
    A.2 Case Knowledge (0–2) per Verbicare doc:
    2 = outstanding amount + DPD/overdue days + loan/repayment context (+ prior PTP if mentioned)
    1 = most info present but gaps (e.g. amount only, or amount without DPD)
    0 = unprepared / missing or incorrect loan details on a collections call
    """
    ctx = ctx or detect_call_context(transcript)
    if not ctx.get("is_collections") or ctx.get("is_wrong_number"):
        return 0

    agent_text = ctx["agent_text"]
    full_lower = ctx["full_lower"]

    has_amount = bool(
        re.search(r"\b\d{3,7}\b", agent_text)
        or re.search(r"\b\d{1,2}[\s,]?\d{3}\b", agent_text)
        or any(
            p in agent_text
            for p in (
                "outstanding", "pending", "due amount", "balance", "emi amount",
                "rupees", "rs.", "rs ", "₹", "payable", "total amount", "loan of",
            )
        )
    )
    has_dpd = bool(
        re.search(r"\b\d{1,4}\s*days?\b", full_lower)
        or re.search(r"\b\d{1,2}\s*months?\b", full_lower)
        or any(
            p in agent_text
            for p in (
                "days past", "dpd", "overdue", "over due", "since", "months overdue",
                "day overdue", "late by", "delay of",
            )
        )
    )
    has_loan_product = any(
        p in agent_text
        for p in (
            "loan", "emi", "installment", "personal loan", "credit", "ok credit",
            "tala", "borrowed", "lms", "product", "repayment", "tenure",
        )
    )
    has_prior_ptp = any(
        p in full_lower
        for p in (
            "previous ptp", "last ptp", "broken promise", "promised earlier",
            "you promised", "last time you said", "commitment was", "did not pay",
            "not paid", "bounced", "broken ptp", "earlier you agreed",
        )
    )
    has_repayment_detail = any(
        p in agent_text
        for p in ("repay", "payment mode", "due date", "installment date", "minimum due")
    )

    rpc_ok = bool(ctx.get("rpc_confirmed"))
    if not rpc_ok and ctx.get("loan_before_rpc"):
        return 0
    if not has_amount:
        return 0

    strong = sum(
        [
            has_amount,
            has_dpd,
            has_loan_product or has_repayment_detail,
            has_prior_ptp,
        ]
    )
    if has_amount and has_dpd and (has_loan_product or has_repayment_detail):
        return 2
    if strong >= 3:
        return 2
    if has_amount and (has_dpd or has_loan_product or has_prior_ptp):
        return 1
    if has_amount and rpc_ok:
        return 1
    return 0


def _count_agent_questions(agent_text: str) -> int:
    return agent_text.count("?")


def score_a3_probing(transcript: str, ctx: dict[str, Any] | None = None) -> int:
    """A.3 Probing (0–3) CRITICAL."""
    ctx = ctx or detect_call_context(transcript)
    if not ctx.get("is_collections") or ctx.get("is_wrong_number"):
        return 0
    agent_text = ctx["agent_text"]
    customer_text = ctx["customer_text"]
    full_lower = ctx["full_lower"]

    probe_cues = (
        "why", "reason", "what happened", "what is the reason", "problem",
        "issue", "unable to pay", "not paying", "delay", "kya problem",
        "kya issue", "what difficulty", "tell me why",
    )
    followup_cues = (
        "can you explain", "what about", "since when", "how long", "which",
        "please tell", "elaborate", "means what", "matlab", "aur kya",
        "any other", "apart from", "besides",
    )
    has_probe = any(p in agent_text for p in probe_cues)
    followups = sum(1 for p in followup_cues if p in agent_text) + max(0, _count_agent_questions(agent_text) - 1)
    customer_explains = any(
        p in customer_text for p in ("because", "lost", "salary", "job", "medical", "app", "no money", "problem")
    )

    if has_probe and followups >= 2 and customer_explains:
        return 3
    if has_probe and (followups >= 1 or customer_explains):
        return 2 if followups >= 1 else 1
    if has_probe:
        return 1
    if any(p in full_lower for p in ("why", "reason")):
        return 1
    return 0


def score_a4_negotiation(transcript: str, ctx: dict[str, Any] | None = None) -> int:
    """A.4 Negotiation (0–3) CRITICAL."""
    ctx = ctx or detect_call_context(transcript)
    if not ctx.get("is_collections") or ctx.get("is_wrong_number"):
        return 0
    agent_text = ctx["agent_text"]

    urgency = ("urgent", "immediately", "today", "as soon", "legal", "cibil", "credit score", "consequences")
    options = ("part payment", "partial", "settlement", "minimum", "installment", "emi option", "one time")
    benefits = ("benefit", "avoid legal", "save cibil", "clear dues", "close loan")
    elements = sum([
        any(p in agent_text for p in urgency),
        any(p in agent_text for p in options),
        any(p in agent_text for p in benefits),
        any(p in agent_text for p in ("pay", "payment", "clear", "settle")),
    ])
    if elements >= 3:
        return 3
    if elements >= 2:
        return 2
    if elements >= 1:
        return 1
    return 0


def score_a5_commitment(transcript: str, ctx: dict[str, Any] | None = None) -> int:
    """A.5 Commitment / PTP (0–3) CRITICAL."""
    ctx = ctx or detect_call_context(transcript)
    if not ctx.get("is_collections") or ctx.get("is_wrong_number"):
        return 0
    full_lower = ctx["full_lower"]
    agent_text = ctx["agent_text"]
    customer_text = ctx["customer_text"]

    pay_intent = any(
        p in full_lower
        for p in (
            "i will pay", "will pay", "pay tomorrow", "pay today", "pay on", "pay by",
            "promise", "commit", "ptp", "payment on", "kar dunga", "kar dungi", "bhar dunga",
        )
    )
    has_amount = bool(re.search(r"\b\d{3,7}\b", full_lower) or "rupee" in full_lower or "rs" in full_lower)
    has_date = bool(
        re.search(r"\b\d{1,2}(?:st|nd|rd|th)?\b", full_lower)
        or any(p in full_lower for p in ("tomorrow", "today", "monday", "tuesday", "next week", "kal", "aaj"))
    )
    has_mode = any(p in full_lower for p in ("upi", "cash", "app", "link", "neft", "imps", "online", "branch"))

    agent_confirms = any(p in agent_text for p in ("confirm", "noted", "recorded", "amount", "date", "mode"))

    if pay_intent and has_amount and has_date and (has_mode or agent_confirms):
        return 3
    if pay_intent and has_amount and has_date:
        return 2
    if pay_intent and (has_amount or has_date):
        return 1
    if pay_intent:
        return 1
    if any(p in full_lower for p in ("call back", "callback", "call later")):
        return 0
    return 0


def score_a6_closing(transcript: str, ctx: dict[str, Any] | None = None) -> int:
    """A.6 Closing (0–2)."""
    ctx = ctx or detect_call_context(transcript)
    if not ctx.get("is_collections") or ctx.get("is_wrong_number"):
        return 0
    agent_lines, _ = _lines_by_speaker(transcript)
    if not agent_lines:
        return 0
    tail = " ".join(agent_lines[-3:]).lower()

    reconfirm = any(p in tail for p in ("confirm", "noted", "amount", "date", "mode", "as discussed", "thank"))
    professional_end = any(p in tail for p in ("thank", "have a nice", "good day", "goodbye", "bye"))
    abrupt = len(agent_lines[-1]) < 15 and not professional_end

    if reconfirm and professional_end:
        return 2
    if reconfirm or professional_end:
        return 1
    if abrupt:
        return 0
    return 1 if len(agent_lines) >= 2 else 0


def score_a7_professionalism(transcript: str, ctx: dict[str, Any] | None = None) -> int:
    """A.7 Professionalism (0–3) CRITICAL."""
    ctx = ctx or detect_call_context(transcript)
    if not ctx.get("is_collections"):
        return 1 if not ctx.get("is_wrong_number") else 0
    full_lower = ctx["full_lower"]
    agent_text = ctx["agent_text"]

    abuse = (
        "idiot", "stupid", "shut up", "bloody", "saala", "bewakoof", "nonsense",
        "threaten", "police station", "jail", "beat", "kill", "destroy",
    )
    if any(p in full_lower for p in abuse):
        return 0

    empathy = any(p in agent_text for p in ("understand", "sorry", "help you", "assist", "please", "request"))
    courteous = any(p in agent_text for p in ("sir", "madam", "thank", "please", "kindly"))
    calm = not any(p in agent_text for p in ("shut", "useless", "fraud"))

    if empathy and courteous and calm:
        return 3
    if courteous and calm:
        return 2
    if courteous or empathy:
        return 1
    return 0


def score_a8_call_handling(transcript: str, ctx: dict[str, Any] | None = None) -> int:
    """A.8 Call Handling (0–1)."""
    ctx = ctx or detect_call_context(transcript)
    if not ctx.get("is_collections") or ctx.get("is_wrong_number"):
        return 0
    agent_lines, _ = _lines_by_speaker(transcript)
    if len(agent_lines) < 2:
        return 0
    agent_text = ctx["agent_text"]
    drift = sum(1 for p in ("weather", "cricket", "movie", "politics") if p in agent_text)
    outcome = any(p in agent_text for p in ("payment", "pay", "ptp", "callback", "amount", "loan", "emi"))
    return 1 if outcome and drift == 0 else 0


def score_a9_troubleshooting(transcript: str, ctx: dict[str, Any] | None = None) -> int:
    """A.9 Troubleshooting (0–1)."""
    ctx = ctx or detect_call_context(transcript)
    if not ctx.get("is_collections") or ctx.get("is_wrong_number"):
        return 0
    full_lower = ctx["full_lower"]
    agent_text = ctx["agent_text"]

    tech_issue = any(p in full_lower for p in ("app not", "link not", "upi fail", "payment fail", "error", "not working"))
    resolution = any(
        p in agent_text
        for p in ("try this link", "send link", "upi", "alternative", "another mode", "escalate", "raise ticket", "whatsapp")
    )
    if tech_issue and resolution:
        return 1
    if resolution and any(p in agent_text for p in ("app", "link", "upi", "payment mode")):
        return 1
    return 0


def detect_ptp_and_flags(transcript: str, ctx: dict[str, Any]) -> tuple[bool, list[str]]:
    """Derive PTP and compliance flags from transcript."""
    flags: set[str] = set()
    full_lower = ctx["full_lower"]
    agent_text = ctx["agent_text"]

    a5 = score_a5_commitment(transcript, ctx)
    ptp = a5 >= 2
    if ptp:
        flags.add("PTP_DETECTED")
    elif ctx.get("is_collections") and not ctx.get("is_wrong_number"):
        flags.add("NO_PTP")

    if any(p in full_lower for p in ("idiot", "stupid", "shut up", "bloody", "threaten", "jail", "beat")):
        flags.add("ABUSE")
    if any(p in full_lower for p in ("legal action", "police", "court", "sue you", "destroy cibil")) and "pay" in agent_text:
        if "threat" not in full_lower:
            pass
        else:
            flags.add("THREAT")

    if ctx.get("loan_before_rpc") or (
        ctx.get("is_collections") and not ctx.get("rpc_confirmed") and any(
            p in agent_text for p in ("outstanding", "overdue", "emi", "loan amount")
        )
    ):
        flags.add("RPC_MISSED")

    third_party = any(p in full_lower for p in ("mother", "father", "wife", "husband", "brother", "sister", "not him", "not her"))
    if third_party:
        if any(p in agent_text for p in ("outstanding", "loan", "emi", "overdue", "legal")):
            flags.add("WRONG_DISCLOSURE")
            flags.add("THIRD_PARTY_BREACH")
        else:
            flags.add("THIRD_PARTY_SAFE")

    return ptp, sorted(flags)


def score_all_parameters(transcript: str, ctx: dict[str, Any] | None = None) -> dict[str, int]:
    ctx = ctx or detect_call_context(transcript)
    if not ctx.get("is_collections") or ctx.get("is_wrong_number"):
        return {
            "A1_opening": score_a1_opening(transcript, ctx),
            "A2_case_knowledge": 0,
            "A3_probing": 0,
            "A4_negotiation": 0,
            "A5_commitment_ptp": 0,
            "A6_closing": 0,
            "A7_professionalism": min(score_a7_professionalism(transcript, ctx), 1),
            "A8_call_handling": 0,
            "A9_troubleshooting": 0,
        }
    return {
        "A1_opening": score_a1_opening(transcript, ctx),
        "A2_case_knowledge": score_a2_case_knowledge(transcript, ctx),
        "A3_probing": score_a3_probing(transcript, ctx),
        "A4_negotiation": score_a4_negotiation(transcript, ctx),
        "A5_commitment_ptp": score_a5_commitment(transcript, ctx),
        "A6_closing": score_a6_closing(transcript, ctx),
        "A7_professionalism": score_a7_professionalism(transcript, ctx),
        "A8_call_handling": score_a8_call_handling(transcript, ctx),
        "A9_troubleshooting": score_a9_troubleshooting(transcript, ctx),
    }


def fix_rpc_compliance_flags(flags: list[str], ctx: dict[str, Any]) -> list[str]:
    """Never tag RPC_MISSED when RPC was confirmed; align with wrong-number calls."""
    normalized = {str(f).upper().strip() for f in flags if f and str(f).upper() != "NONE"}

    if ctx.get("rpc_confirmed"):
        normalized.discard("RPC_MISSED")
        if "THIRD_PARTY_BREACH" not in normalized:
            normalized.discard("WRONG_DISCLOSURE")
    elif ctx.get("is_wrong_number"):
        normalized.discard("RPC_MISSED")
    elif ctx.get("is_collections") and (
        ctx.get("loan_before_rpc") or (ctx.get("rpc_attempted") and not ctx.get("rpc_confirmed"))
    ):
        normalized.add("RPC_MISSED")
    elif not ctx.get("is_collections"):
        normalized.discard("RPC_MISSED")

    return sorted(normalized) if normalized else ["NONE"]


def apply_non_collections_guardrail(result: dict, ctx: dict[str, Any]) -> dict:
    """Non-collections calls must not score 100% or high — cap and flag."""
    if ctx.get("is_collections") and not ctx.get("is_wrong_number"):
        return result

    flags = {str(f).upper() for f in (result.get("compliance_flags") or []) if f and str(f).upper() != "NONE"}
    flags.add("NOT_COLLECTIONS")
    flags.discard("RPC_MISSED")
    flags.discard("PTP_DETECTED")
    has_third_party_breach = "THIRD_PARTY_BREACH" in flags or "WRONG_DISCLOSURE" in flags

    scores = dict(result.get("scores") or {})
    is_third_party_safe = "THIRD_PARTY_SAFE" in flags
    if (ctx.get("is_wrong_number") or is_third_party_safe) and not has_third_party_breach:
        # Senior-required behavior: safe third-party/wrong-number handling should not be penalized.
        scores = {
            "A1_opening": 2,
            "A2_case_knowledge": 2,
            "A3_probing": 3,
            "A4_negotiation": 3,
            "A5_commitment_ptp": 3,
            "A6_closing": 2,
            "A7_professionalism": 3,
            "A8_call_handling": 1,
            "A9_troubleshooting": 1,
        }
        total = 20
        result["grade"] = "Excellent"
        flags.add("THIRD_PARTY_SAFE")
    else:
        scores["A2_case_knowledge"] = 0
        scores["A3_probing"] = 0
        scores["A4_negotiation"] = 0
        scores["A5_commitment_ptp"] = 0
        scores["A9_troubleshooting"] = 0
        scores["A1_opening"] = min(scores.get("A1_opening", 0), score_a1_opening("", ctx), 1)
        scores["A6_closing"] = min(scores.get("A6_closing", 0), 1)
        scores["A7_professionalism"] = min(scores.get("A7_professionalism", 0), 1)
        scores["A8_call_handling"] = min(scores.get("A8_call_handling", 0), 1)
        total = min(sum(scores.values()), 4)
        result["grade"] = "Poor" if total <= 4 else result.get("grade", "Poor")

    result["scores"] = scores
    result["total_score"] = total
    result["total_score_pct"] = int(round((total / 20) * 100))
    result["critical_fail"] = False
    result["ptp_detected"] = False
    result["compliance_flags"] = sorted(flags)
    if ctx.get("is_wrong_number"):
        result["disposition"] = "WRONG_NUMBER"
        # Strip RPC-related issues for wrong-number calls.
        issues = [x for x in _as_list(result.get("key_issues")) if "rpc" not in str(x).lower()]
        if not issues and not has_third_party_breach:
            issues = ["Correctly identified as third-party / wrong-number call"]
        result["key_issues"] = issues[:8]
    result["ai_detection"] = list(dict.fromkeys(
        (result.get("ai_detection") or []) + ["Non-Collections Call"]
    ))
    result["ai_suggestion"] = (
        "No loan/EMI/collections dialogue detected in the transcript. "
        "If this file came from a collections queue, verify the recording and reprocess."
    )
    result["summary"] = (
        (result.get("summary") or "")
        + " [Guardrail: not a collections conversation — scores capped.]"
    ).strip()
    return result


def _is_early_customer_decline(transcript: str, ctx: dict[str, Any]) -> bool:
    """
    Customer is busy/declines quickly after opening.
    Should not be marked as pure agent failure.
    """
    full = (transcript or "").lower()
    customer_text = (ctx.get("customer_text") or "").lower()
    agent_lines, customer_lines = _lines_by_speaker(transcript)
    decline_cues = (
        "call later", "callback", "call back", "i am busy", "i'm busy",
        "not free", "can't talk", "cannot talk", "talk later", "later please",
        "i will call you", "disconnect", "cut the call",
    )
    has_decline = any(p in customer_text or p in full for p in decline_cues)
    short_interaction = len(agent_lines) <= 4 and len(customer_lines) <= 4
    opening_done = bool(ctx.get("rpc_attempted")) or any(
        p in (ctx.get("agent_text") or "")
        for p in ("speaking with", "am i speaking", "is this")
    )
    return bool(has_decline and short_interaction and opening_done)


def apply_phase1_scoring(result: dict, transcript: str, filename_hint: str = "") -> dict:
    """Apply full rule-based scoring A1–A9 + compliance flags + guardrails."""
    kpis = detect_call_kpis(transcript, filename_hint=filename_hint)
    ctx = kpis.get("_ctx") or detect_call_context(transcript, filename_hint)
    ctx["rpc_confirmed"] = bool(kpis.get("rpc_confirmed"))
    ctx["rpc_attempted"] = bool(kpis.get("rpc_attempted"))

    scores = apply_sequential_parameter_gating(score_all_parameters(transcript, ctx), ctx)
    opening = kpis_to_opening_audit(kpis)
    result["scores"] = scores
    result["opening_audit"] = opening

    ptp, detected_flags = detect_ptp_and_flags(transcript, ctx)
    llm_flags = _as_list(result.get("compliance_flags"))
    merged = fix_rpc_compliance_flags(list(set(llm_flags + detected_flags)), ctx)
    result["compliance_flags"] = merged
    result["ptp_detected"] = ptp or bool(result.get("ptp_detected"))

    if scores.get("A7_professionalism", 0) == 0:
        flags_set = set(_as_list(result["compliance_flags"]))
        if any(p in ctx["full_lower"] for p in ("idiot", "stupid", "threaten", "abuse", "bloody")):
            flags_set.add("ABUSE")
        result["compliance_flags"] = sorted(flags_set) if flags_set else ["NONE"]

    result = apply_non_collections_guardrail(result, ctx)

    scores = result["scores"]
    early_decline = _is_early_customer_decline(transcript, ctx)
    if early_decline and not ctx.get("is_wrong_number"):
        # Not agent fault: customer declines early despite opening effort.
        scores["A1_opening"] = max(scores.get("A1_opening", 0), 1)
        scores["A3_probing"] = max(scores.get("A3_probing", 0), 1)
        scores["A4_negotiation"] = max(scores.get("A4_negotiation", 0), 1)
        scores["A5_commitment_ptp"] = max(scores.get("A5_commitment_ptp", 0), 1)
        scores["A6_closing"] = max(scores.get("A6_closing", 0), 1)
        scores["A7_professionalism"] = max(scores.get("A7_professionalism", 0), 2)
        scores["A8_call_handling"] = max(scores.get("A8_call_handling", 0), 1)
        result["scores"] = scores
        if str(result.get("disposition") or "").upper() in {"OTHER", ""}:
            result["disposition"] = "CALLBACK"
        det = list(_as_list(result.get("ai_detection")))
        if "CUSTOMER_BUSY_EARLY_EXIT" not in det:
            det.append("CUSTOMER_BUSY_EARLY_EXIT")
        result["ai_detection"] = det

    total = sum(scores.values())
    result["total_score"] = total
    result["total_score_pct"] = int(round((total / 20) * 100))
    result["grade"] = (
        "Excellent" if total >= 18 else "Good" if total >= 14
        else "Needs Improvement" if total >= 8 else "Poor"
    )
    critical = ["A3_probing", "A4_negotiation", "A5_commitment_ptp", "A7_professionalism"]
    if ctx.get("is_collections") and not ctx.get("is_wrong_number"):
        result["critical_fail"] = False if early_decline else bool(any(scores.get(k, 0) == 0 for k in critical))
    else:
        result["critical_fail"] = False

    missing_opening = []
    if ctx.get("is_collections") and not ctx.get("is_wrong_number"):
        if not opening.get("disclaimer_given"):
            missing_opening.append("Disclaimer missing")
        if not opening.get("agent_intro_done"):
            missing_opening.append("Agent intro missing")
        if not opening.get("rpc_confirmed"):
            missing_opening.append("RPC not confirmed")
    if missing_opening:
        issues = list(_as_list(result.get("key_issues")))
        for item in missing_opening:
            if item not in issues:
                issues.append(item)
        result["key_issues"] = issues[:8]

    # Keep key-issues consistent with computed opening audit.
    issues = list(_as_list(result.get("key_issues")))
    if opening.get("rpc_confirmed"):
        issues = [x for x in issues if "rpc" not in str(x).lower()]
    else:
        if not any("rpc" in str(x).lower() for x in issues):
            issues.append("RPC not confirmed")
    result["key_issues"] = issues[:8]

    # Keep ai_detection aligned with final RPC decision.
    detection = [str(x).upper() for x in _as_list(result.get("ai_detection"))]
    if opening.get("rpc_confirmed"):
        detection = [
            d for d in detection
            if "RPC_MISSED" not in d
            and "RPC NOT CONFIRMED" not in d
            and "WRONG_DISCLOSURE" not in d
        ]
    result["ai_detection"] = detection or ["NONE"]
    if ctx.get("is_collections"):
        result["ai_detection"] = [
            d for d in _as_list(result.get("ai_detection"))
            if str(d).strip().lower() not in {"non-collections call", "not_collections"}
        ] or ["NONE"]

    result["_scoring_calibration"] = {
        "phase": "A1_A9_verbicare_v11_kpi",
        **scores,
        "opening_audit": opening,
        "rpc_confirmed": ctx.get("rpc_confirmed"),
        "is_collections": ctx.get("is_collections"),
        "is_wrong_number": ctx.get("is_wrong_number"),
    }
    result = merge_kpis_into_scoring_result(result, kpis)
    return result


apply_rule_scoring = apply_phase1_scoring


def _as_list(v):
    if not v:
        return []
    if isinstance(v, list):
        return [x for x in v if x]
    if isinstance(v, str):
        return [v] if v.upper() != "NONE" else []
    return [v]
