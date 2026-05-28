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


def detect_call_context(transcript: str) -> dict[str, Any]:
    """Detect RPC, collections vs non-collections, and early disclosure."""
    agent_lines, customer_lines = _lines_by_speaker(transcript)
    agent_text = " ".join(agent_lines).lower()
    customer_text = " ".join(customer_lines).lower()
    full_lower = (transcript or "").lower()

    collections_cues = (
        "loan", "emi", "outstanding", "overdue", "payment", "due amount", "pending",
        "ok credit", "tala", "collection", "borrower", "installment", "settlement",
        "cibil", "legal notice", "days past", "dpd", "rupees", "rs ", "₹",
        "noc", "default", "recovery", "pay today", "pay tomorrow",
    )
    non_collection_cues = (
        "wrong number", "delivery", "courier", "insurance claim", "doctor appointment",
        "hospital appointment", "customer care", "tech support", "survey", "feedback call",
        "not a loan", "no loan", "who are you calling", "marketing call", "sales pitch",
    )
    is_collections = any(c in full_lower for c in collections_cues)
    if any(c in full_lower for c in non_collection_cues) and not any(
        c in full_lower for c in ("emi", "outstanding", "overdue", "loan amount", "dpd", "borrower")
    ):
        is_collections = False

    wrong_number_cues = (
        "wrong number", "galat number", "not this person", "not him", "not her",
        "number change", "changed my number", "who is this", "don't know him",
        "don't know her", "no such person", "not available", "passed away",
        "deceased", "wrong party",
    )
    is_wrong_number = any(c in full_lower for c in wrong_number_cues)

    rpc_question_cues = (
        "am i speaking", "is this", "speaking with", "confirm your name",
        "may i speak", "are you mr", "are you ms", "are you mrs", "your good name",
        "naam confirm", "aap hi", "kya main", "right party", "borrower",
        "customer name", "who am i speaking",
    )
    rpc_attempted = any(c in agent_text for c in rpc_question_cues)

    rpc_confirm_customer = (
        "yes", "haan", "ji", "speaking", "this is", "main hoon", "bol raha",
        "bol rahi", "correct", "right", "myself", "that's me", "same person",
        "haan bol", "haan ji", "main hi", "yahi hoon", "yahi hun", "sahi number",
        "correct number", "who is speaking", "i am the", "mera naam",
    )
    rpc_confirmed = False
    if rpc_attempted and customer_lines:
        for cust in customer_lines[:6]:
            cl = cust.lower()
            if any(c in cl for c in rpc_confirm_customer) and len(cl) < 120:
                if not any(w in cl for w in wrong_number_cues):
                    rpc_confirmed = True
                    break
    if any(c in agent_text for c in ("thank you mr", "thank you ms", "thank you shri", "dear mr", "dear ms")):
        rpc_confirmed = True
    if is_wrong_number:
        rpc_confirmed = False

    loan_agent_cues = ("outstanding", "overdue", "emi", "loan amount", "pending amount", "due is", "balance is")
    first_rpc_idx = len(full_lower)
    first_loan_idx = len(full_lower)
    for i, line in enumerate(agent_lines):
        ll = line.lower()
        if first_rpc_idx == len(full_lower) and any(c in ll for c in rpc_question_cues):
            first_rpc_idx = full_lower.find(ll[:40]) if ll else first_rpc_idx
        if first_loan_idx == len(full_lower) and any(c in ll for c in loan_agent_cues):
            first_loan_idx = full_lower.find(ll[:40]) if ll else first_loan_idx
    loan_before_rpc = (
        is_collections
        and not rpc_confirmed
        and any(c in agent_text for c in loan_agent_cues)
        and (not rpc_attempted or first_loan_idx < first_rpc_idx)
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


def audit_opening_elements(transcript: str, ctx: dict[str, Any] | None = None) -> dict[str, bool]:
    """Opening checklist per Verbicare doc (disclaimer, intro, name, RPC)."""
    ctx = ctx or detect_call_context(transcript)
    agent_text = ctx["agent_text"]
    name_detected = _customer_name_mentioned(agent_text)
    print(
        f"[OPENING_AUDIT] customer_name_used={name_detected} | "
        f"agent_text_head={agent_text[:160]!r}",
        flush=True,
    )
    return {
        "disclaimer_given": any(
            p in agent_text
            for p in (
                "recorded", "monitored", "quality purpose", "training", "this call is",
                "call may be recorded", "for quality", "disclaimer", "recorded line",
            )
        ),
        "agent_intro_done": any(
            p in agent_text
            for p in (
                "speaking on behalf", "calling from", "this is", "my name is", "i am ",
                "on behalf of", "from ok credit", "from tala", "from the bank", "namaste",
            )
        ),
        "customer_name_used": name_detected,
        "rpc_confirmed": bool(ctx.get("rpc_confirmed")),
        "rpc_attempted": bool(ctx.get("rpc_attempted")),
        "is_collections": bool(ctx.get("is_collections")),
    }


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
    if ctx.get("is_wrong_number") and not has_third_party_breach:
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
    result["summary"] = (
        (result.get("summary") or "")
        + " [Guardrail: not a collections conversation — scores capped.]"
    ).strip()
    return result


def apply_phase1_scoring(result: dict, transcript: str) -> dict:
    """Apply full rule-based scoring A1–A9 + compliance flags + guardrails."""
    ctx = detect_call_context(transcript)
    scores = apply_sequential_parameter_gating(score_all_parameters(transcript, ctx), ctx)
    opening = audit_opening_elements(transcript, ctx)
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
    total = sum(scores.values())
    result["total_score"] = total
    result["total_score_pct"] = int(round((total / 20) * 100))
    result["grade"] = (
        "Excellent" if total >= 18 else "Good" if total >= 14
        else "Needs Improvement" if total >= 8 else "Poor"
    )
    critical = ["A3_probing", "A4_negotiation", "A5_commitment_ptp", "A7_professionalism"]
    if ctx.get("is_collections") and not ctx.get("is_wrong_number"):
        result["critical_fail"] = bool(any(scores.get(k, 0) == 0 for k in critical))
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

    result["_scoring_calibration"] = {
        "phase": "A1_A9_verbicare_v10",
        **scores,
        "opening_audit": opening,
        "rpc_confirmed": ctx.get("rpc_confirmed"),
        "is_collections": ctx.get("is_collections"),
        "is_wrong_number": ctx.get("is_wrong_number"),
    }
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
