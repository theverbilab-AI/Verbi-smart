"""
Canonical speaker attribution layer.

Single source of truth for deciding whether a transcript line was spoken by the
Agent or the Customer. The pipeline is:

    raw transcript -> structural split -> speaker correction (this module)
                   -> verified transcript -> QA scoring

Every verified turn carries a `speaker`, a `confidence` (0..1) and a human
`reason`. Low-confidence turns drive the `review_required` flag so uncertain
calls are never auto-approved.

The frontend renders these verified turns *verbatim* — it must NOT re-classify
speakers, otherwise the displayed labels diverge from the audited ones.
"""
from __future__ import annotations

import os
import re
from collections import Counter

# Per-line attribution logging (original -> corrected, confidence, reason).
# Enable with CARE_SPEAKER_DEBUG=1 to diagnose mislabeled calls.
_SPEAKER_DEBUG = os.getenv("CARE_SPEAKER_DEBUG", "0") == "1"

# A two-speaker call where one speaker owns almost every line is almost
# certainly a diarization failure — flag it for review instead of trusting it.
SINGLE_SPEAKER_DOMINANCE = float(os.getenv("CARE_SPEAKER_DOMINANCE", "0.95"))
DOMINANCE_MIN_TURNS = int(os.getenv("CARE_SPEAKER_DOMINANCE_MIN_TURNS", "5"))

# ── Cue tables ──────────────────────────────────────────────────────────────
# Each cue is (regex, weight, reason). Higher weight = stronger signal.

AGENT_CUES: list[tuple[str, int, str]] = [
    (r"\b(i am calling from|i'?m calling from|calling from|calling on behalf)\b", 7, "agent: calling from"),
    (r"\b(on behalf of|speaking on behalf)\b", 8, "agent: on behalf of"),
    (r"\b(this call is being recorded|call is being recorded|call is recorded|recorded for (quality|training))\b", 8, "agent: recording disclaimer"),
    (r"\b(you have to pay|you need to pay|kindly pay|please pay|pay (today|now|immediately)|make (the|your) payment|clear (your|the) (dues|outstanding|payment|loan))\b", 6, "agent: payment demand"),
    (r"\b(your (emi|loan|outstanding|overdue|dues|account|payment|installment)|amount (is )?due|payment is (due|pending|overdue)|dpd|days past due)\b", 6, "agent: account/loan reference"),
    (r"\b(am i speaking (with|to)|may i (speak|talk) (with|to)|are you (mr|mrs|ms|miss)\b|is this (mr|mrs|ms)\b)", 5, "agent: RPC check"),
    (r"\b(from (tala|the bank|the company|collections|recovery)|recovery team|collections team)\b", 6, "agent: company identity"),
    (r"\b(noted your ptp|i (will|have) record(ed)?|i have noted|i am noting)\b", 5, "agent: agent action"),
]

CUSTOMER_CUES: list[tuple[str, int, str]] = [
    (r"\bmy (father|mother|husband|wife|son|daughter|papa|mummy|dad|mom|brother|sister)\b.{0,40}\b(passed away|expired|died|death|no more|hospital|sick|ill|admitted)\b", 9, "customer: family bereavement/illness"),
    (r"\b(passed away|expired on|he expired|she expired|guzar ga|chal base|nahi rahe|nahi rahi)\b", 7, "customer: bereavement"),
    (r"\b(my financial condition|financial (problem|difficulty|crisis|trouble)|financially (weak|down|broke)|paisa nahi hai|paise nahi hai|don'?t have (money|funds|cash)|no money|naukri (chali gayi|nahi hai)|lost my job|job (chali gayi|gone|nahi))\b", 8, "customer: financial hardship"),
    (r"\b(i will try|i'?ll try|i will see|koshish kar(unga|ungi)|try kar(unga|ungi)|dekhta hu|dekhti hu)\b", 6, "customer: weak commitment"),
    (r"\b(i will pay|i'?ll pay|i will (give|do) (it|the payment)|main (pay )?kar(unga|ungi)|de (dunga|dungi)|paisa de (dunga|dungi)|arrange kar(unga|ungi)|pay kar dunga)\b", 6, "customer: payment commitment"),
    (r"\b(i am having (trouble|difficulty|a problem|a little difficulty)|having (trouble|difficulty)|i am in (trouble|difficulty)|pareshani|dikkat (hai|ho)|takleef)\b", 7, "customer: hardship"),
    (r"\b(i spent (the )?money|spent (the )?money|paisa kharch (ho|kar)|money (was|got) spent|kharch ho gaya)\b", 6, "customer: spent money"),
    (r"\b(wrong number|galat number|who are you|who is (this|speaking|calling)|what do you want|kaun bol rah[ai]|change this number|don'?t call (me|this)|stop calling)\b", 8, "customer: identity/objection"),
    (r"\b(give me (some )?time|thoda (time|samay)|kuch din|some (days|time)|next month|agle mahine|baad mein)\b", 5, "customer: asking for time"),
    (r"\b(yes,? tell me|haan ji|haan bolo|boliye|main bol rah[ai]|mera naam|yes speaking|speaking\.?$)\b", 6, "customer: RPC answer / self-id"),
]

# Probing questions: in a collections context these are asked by the AGENT.
# (Identity questions like "who are you" stay Customer via CUSTOMER_CUES above.)
PROBING_AGENT_CUES: list[tuple[str, int, str]] = [
    (r"\bwhat is the (problem|issue|matter|reason)\b", 6, "agent: probing question (problem)"),
    (r"\bwhat happened\b", 5, "agent: probing question (what happened)"),
    (r"\bwhen (will|can|are|would) you (pay|paying|clear|going to pay|make the payment)\b", 7, "agent: probing question (when pay)"),
    (r"\bby when (will|can|are) you\b", 6, "agent: probing question (by when)"),
    (r"\bhow much (can|will|are) you (pay|give|arrange|going to pay)\b", 6, "agent: probing question (how much)"),
    (r"\bwhy (did(n'?t| not)? you|have(n'?t| not)? you|are you not|aren'?t you) (pay|paid|paying|clear(ed)?)\b", 6, "agent: probing question (why not paid)"),
    (r"\bwhen did (your|his|her|the) .{0,25}(expire|pass(ed)? away|die|no more)\b", 6, "agent: probing question (when death)"),
    (r"\b(have|did) you (made|make|done|do|complete[d]?) (the )?payment\b", 6, "agent: probing question (payment done)"),
]

_SHORT_ACK_RE = re.compile(r"^(yes|yeah|yep|no|nope|okay|ok|haan|haan ji|ji|ho|hmm|hello)[\s.,!]*$", re.I)

# Confidence thresholds
LINE_LOW_CONF = 0.50          # a turn below this is "low confidence"
CALL_MIN_CONF_REVIEW = 0.45   # any turn below this forces review
DEFAULT_OPENING_SPEAKER = "Agent"  # collections agent normally opens the call


def _compile(table: list[tuple[str, int, str]]) -> list[tuple[re.Pattern, int, str]]:
    return [(re.compile(pat, re.I), w, reason) for pat, w, reason in table]


_AGENT = _compile(AGENT_CUES)
_CUSTOMER = _compile(CUSTOMER_CUES)
_PROBING = _compile(PROBING_AGENT_CUES)


def _hits(text_low: str, table: list[tuple[re.Pattern, int, str]]) -> list[tuple[int, str]]:
    return [(w, reason) for rx, w, reason in table if rx.search(text_low)]


def classify_line(text: str, prev_speaker: str | None = None) -> dict:
    """Classify a single line. Returns {speaker, confidence, reason}."""
    low = (text or "").lower().strip()
    if not low:
        return {"speaker": prev_speaker or DEFAULT_OPENING_SPEAKER, "confidence": 0.4, "reason": "empty line"}

    agent_hits = _hits(low, _AGENT) + _hits(low, _PROBING)
    customer_hits = _hits(low, _CUSTOMER)

    # A bare acknowledgement ("Yes.", "Okay.") is the customer answering the agent.
    if _SHORT_ACK_RE.match(low) and "hello" not in low:
        customer_hits.append((4, "customer: short acknowledgement"))

    a = sum(w for w, _ in agent_hits)
    c = sum(w for w, _ in customer_hits)

    if a == 0 and c == 0:
        # Do not let continuity confidently spread one label across a full call.
        # Legacy text-only fallback may still need a speaker for display, but the
        # low confidence + attribution summary below will force manual review.
        return {
            "speaker": prev_speaker or DEFAULT_OPENING_SPEAKER,
            "confidence": 0.35,
            "reason": "uncertain speaker (no cue; text fallback)",
        }

    if a >= c:
        speaker, win, lose, hits = "Agent", a, c, agent_hits
    else:
        speaker, win, lose, hits = "Customer", c, a, customer_hits

    margin = win - lose
    confidence = min(0.96, 0.6 + 0.07 * margin)
    if a > 0 and c > 0:
        # conflicting evidence from both sides — lower trust
        confidence = max(0.45, confidence - 0.2)

    hits = sorted(hits, key=lambda h: h[0], reverse=True)
    reason = "; ".join(r for _, r in hits[:2]) or "weighted cues"
    return {"speaker": speaker, "confidence": round(confidence, 2), "reason": reason}


def _parse_labelled(labelled: str) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    for raw in (labelled or "").splitlines():
        m = re.match(r"^(agent|customer)\s*:\s*(.*)$", raw.strip(), re.I)
        if m:
            text = (m.group(2) or "").strip()
            if text:
                out.append((m.group(1).title(), text))
    return out


def attribute_transcript(labelled: str) -> list[dict]:
    """Turn a labelled transcript into verified turns with confidence + reason.

    Each turn: {speaker, text, confidence, reason, original_speaker, changed}.
    """
    lines = _parse_labelled(labelled)
    turns: list[dict] = []
    prev: str | None = None
    for original, text in lines:
        res = classify_line(text, prev)
        res["text"] = text
        res["original_speaker"] = original
        res["changed"] = original != res["speaker"]
        turns.append(res)
        prev = res["speaker"]

    if _SPEAKER_DEBUG:
        for i, t in enumerate(turns):
            print(
                f"[ATTR] line={i} orig={t.get('original_speaker')} -> {t.get('speaker')} "
                f"conf={t.get('confidence')} reason={t.get('reason')} | {(t.get('text') or '')[:70]}",
                flush=True,
            )

    return turns


def summarize_attribution(turns: list[dict]) -> dict:
    """Aggregate confidence stats and decide if speaker attribution needs review."""
    if not turns:
        return {
            "min_confidence": 1.0,
            "avg_confidence": 1.0,
            "low_confidence_lines": 0,
            "changed_lines": 0,
            "total_lines": 0,
            "review_required": False,
        }
    confs = [float(t.get("confidence", 1.0)) for t in turns]
    low = sum(1 for c in confs if c < LINE_LOW_CONF)
    changed = sum(1 for t in turns if t.get("changed"))
    min_c = min(confs)
    sources = sorted({str(t.get("attribution_source") or "unknown") for t in turns})
    audio_diarization_used = "audio_diarization" in sources

    # Speaker distribution — a near-monologue on a multi-line call is a red flag.
    counts = Counter(t.get("speaker") for t in turns)
    dominant_speaker, dominant_n = counts.most_common(1)[0]
    dominant_share = dominant_n / len(turns)
    has_agent = counts.get("Agent", 0) > 0
    has_customer = counts.get("Customer", 0) > 0
    missing_required_speakers = len(turns) >= DOMINANCE_MIN_TURNS and not (has_agent and has_customer)
    single_speaker_dominant = (
        len(turns) >= DOMINANCE_MIN_TURNS and dominant_share >= SINGLE_SPEAKER_DOMINANCE
    )
    speaker_attribution_failed = bool(missing_required_speakers or single_speaker_dominant)

    review = (
        min_c < CALL_MIN_CONF_REVIEW
        or low >= 2
        or (len(turns) >= 4 and changed / len(turns) > 0.45)
        or speaker_attribution_failed
    )
    return {
        "min_confidence": round(min_c, 2),
        "avg_confidence": round(sum(confs) / len(confs), 2),
        "low_confidence_lines": low,
        "changed_lines": changed,
        "total_lines": len(turns),
        "attribution_sources": sources,
        "audio_diarization_used": bool(audio_diarization_used),
        "speaker_counts": dict(counts),
        "has_agent": bool(has_agent),
        "has_customer": bool(has_customer),
        "missing_required_speakers": bool(missing_required_speakers),
        "dominant_speaker": dominant_speaker,
        "dominant_share": round(dominant_share, 2),
        "single_speaker_dominant": bool(single_speaker_dominant),
        "speaker_attribution_failed": speaker_attribution_failed,
        "review_required": bool(review),
    }


def to_labelled_text(turns: list[dict]) -> str:
    """Render verified turns back to `Speaker: text` lines."""
    return "\n".join(f"{t['speaker']}: {t['text']}" for t in turns if t.get("text"))


# Stored turns below this confidence or with bad speaker balance need audio re-diarization.
BAD_TURN_MAX_CONF = float(os.getenv("CARE_BAD_TURN_MAX_CONF", "0.60"))
BAD_TURN_MAX_DOMINANCE = float(os.getenv("CARE_BAD_TURN_MAX_DOMINANCE", "0.90"))


def needs_audio_reprocess(speaker_turns: list | None) -> bool:
    """True when speaker_turns are missing or came from legacy text fallback / bad balance."""
    try:
        from diarization import AUDIO_DIARIZATION_SOURCE, CARE_USE_DIARIZATION
    except ImportError:
        return False
    if not CARE_USE_DIARIZATION:
        return False

    turns = [t for t in (speaker_turns or []) if t and str(t.get("text") or "").strip()]
    if not turns:
        return True

    for t in turns:
        src = str(t.get("attribution_source") or "").strip()
        if src != AUDIO_DIARIZATION_SOURCE:
            return True

    confs = [
        float(t["confidence"])
        for t in turns
        if isinstance(t.get("confidence"), (int, float))
    ]
    if confs and min(confs) <= BAD_TURN_MAX_CONF:
        return True

    if len(turns) >= 5:
        counts = Counter(str(t.get("speaker") or "") for t in turns)
        dominant_share = max(counts.values()) / len(turns)
        if dominant_share >= BAD_TURN_MAX_DOMINANCE:
            return True

    return False


def corrections_from_turns(turns: list[dict]) -> list[dict]:
    """Subset of turns whose speaker was changed from the raw diarization."""
    return [
        {
            "from": t.get("original_speaker"),
            "to": t.get("speaker"),
            "confidence": t.get("confidence"),
            "reason": t.get("reason"),
            "text": (t.get("text") or "")[:120],
        }
        for t in turns
        if t.get("changed")
    ]
