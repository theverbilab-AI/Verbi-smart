"""
CARE rule-based scoring calibration — parameter-by-parameter.

Calibrated parameters: A1 Opening, A2 Case Knowledge, RPC flags, non-collections guardrail.
Further parameters (A3–A9) per Verbicare Changes doc.
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
    )
    is_collections = any(c in full_lower for c in collections_cues)

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

    scores = dict(result.get("scores") or {})
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

    flags = {str(f).upper() for f in (result.get("compliance_flags") or []) if f and str(f).upper() != "NONE"}
    flags.add("NOT_COLLECTIONS")
    flags.discard("RPC_MISSED")
    flags.discard("PTP_DETECTED")

    result["scores"] = scores
    result["total_score"] = total
    result["total_score_pct"] = int(round((total / 20) * 100))
    result["grade"] = "Poor" if total <= 4 else result.get("grade", "Poor")
    result["critical_fail"] = False
    result["ptp_detected"] = False
    result["compliance_flags"] = sorted(flags)
    if ctx.get("is_wrong_number"):
        result["disposition"] = "WRONG_NUMBER"
    result["ai_detection"] = list(dict.fromkeys(
        (result.get("ai_detection") or []) + ["Non-Collections Call"]
    ))
    result["summary"] = (
        (result.get("summary") or "")
        + " [Guardrail: not a collections conversation — scores capped.]"
    ).strip()
    return result


def apply_phase1_scoring(result: dict, transcript: str) -> dict:
    """
    Rule-based calibration: A1 Opening, A2 Case Knowledge, RPC flags, non-collections guardrail.
    """
    ctx = detect_call_context(transcript)
    scores = dict(result.get("scores") or {})

    scores["A1_opening"] = score_a1_opening(transcript, ctx)
    if ctx.get("is_collections") and not ctx.get("is_wrong_number"):
        scores["A2_case_knowledge"] = score_a2_case_knowledge(transcript, ctx)
    result["scores"] = scores

    flags = _as_list(result.get("compliance_flags"))
    result["compliance_flags"] = fix_rpc_compliance_flags(flags, ctx)

    if ctx.get("rpc_confirmed") and "RPC_MISSED" in str(result.get("compliance_flags")):
        result["compliance_flags"] = fix_rpc_compliance_flags([], ctx)

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

    result["_scoring_calibration"] = {
        "phase": "A1_A2_done",
        "A1_opening": scores.get("A1_opening"),
        "A2_case_knowledge": scores.get("A2_case_knowledge"),
        "rpc_confirmed": ctx.get("rpc_confirmed"),
        "is_collections": ctx.get("is_collections"),
        "is_wrong_number": ctx.get("is_wrong_number"),
    }
    return result


def _as_list(v):
    if not v:
        return []
    if isinstance(v, list):
        return [x for x in v if x]
    if isinstance(v, str):
        return [v] if v.upper() != "NONE" else []
    return [v]
