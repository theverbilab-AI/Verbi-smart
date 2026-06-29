"""
Tests for the canonical speaker attribution layer (speaker_attribution.py).

Covers the exact scenario requested:
- Agent asks "when did your father expire"  -> Agent
- Customer answers "mine expired on the 24th" -> Customer
Plus: probing questions = Agent, hardship = Customer, low-confidence fallback,
review_required, and the full format_labelled_transcript pipeline.
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from speaker_attribution import (  # noqa: E402
    attribute_transcript,
    classify_line,
    summarize_attribution,
    to_labelled_text,
)
from processor import format_labelled_transcript  # noqa: E402
from qa_validation import validate_collections_audit  # noqa: E402


def main():
    ok = True

    print("=== Probing questions are AGENT (collections context) ===")
    agent_questions = [
        "What is the problem?",
        "When will you pay the amount?",
        "By when will you pay?",
        "How much can you pay this month?",
        "When did your father expire?",
        "Have you made the payment?",
    ]
    for q in agent_questions:
        res = classify_line(q, prev_speaker="Customer")
        good = res["speaker"] == "Agent"
        ok &= good
        print(f"  {'PASS' if good else 'FAIL'} {q!r} -> {res['speaker']} ({res['confidence']}) [{res['reason']}]")

    print("\n=== Identity questions stay CUSTOMER ===")
    customer_questions = ["Who are you?", "Who is speaking?", "What do you want?"]
    for q in customer_questions:
        res = classify_line(q, prev_speaker="Agent")
        good = res["speaker"] == "Customer"
        ok &= good
        print(f"  {'PASS' if good else 'FAIL'} {q!r} -> {res['speaker']} ({res['confidence']}) [{res['reason']}]")

    print("\n=== Hardship statements are CUSTOMER ===")
    customer_lines = [
        "My father passed away on the 24th.",
        "My financial condition is very bad, sir.",
        "I will try, madam.",
        "I am having a little difficulty, madam.",
        "I spent the money on my father's treatment.",
    ]
    for line in customer_lines:
        res = classify_line(line, prev_speaker="Agent")
        good = res["speaker"] == "Customer"
        ok &= good
        print(f"  {'PASS' if good else 'FAIL'} {line!r} -> {res['speaker']} ({res['confidence']}) [{res['reason']}]")

    print("\n=== Agent indicators are AGENT ===")
    agent_lines = [
        "I am calling from Tala regarding your loan.",
        "I am speaking on behalf of the bank.",
        "This call is being recorded for quality.",
        "You have to pay the overdue amount today.",
    ]
    for line in agent_lines:
        res = classify_line(line, prev_speaker="Customer")
        good = res["speaker"] == "Agent"
        ok &= good
        print(f"  {'PASS' if good else 'FAIL'} {line!r} -> {res['speaker']} ({res['confidence']}) [{res['reason']}]")

    print("\n=== Father-death scenario: full attribution ===")
    # Raw diarization (deliberately mislabeled, as the LLM often does):
    raw = (
        "Agent: Hello, am I speaking with Mr. Sharma?\n"
        "Customer: Yes, tell me.\n"
        "Agent: I am calling from Tala about your overdue loan. This call is being recorded.\n"
        "Customer: My father passed away on the 24th, sir.\n"          # often mis-tagged Agent
        "Customer: When did your father expire?\n"                     # this is the AGENT probing
        "Agent: My financial condition is very bad right now.\n"       # this is the CUSTOMER
        "Customer: I will try to pay something next month.\n"
    )
    turns = attribute_transcript(raw)
    for t in turns:
        flag = " (changed)" if t["changed"] else ""
        print(f"  {t['speaker']:8} ({t['confidence']}) {t['text']}{flag}  [{t['reason']}]")

    by_text = {t["text"]: t["speaker"] for t in turns}
    checks = {
        "My father passed away on the 24th, sir.": "Customer",
        "When did your father expire?": "Agent",
        "My financial condition is very bad right now.": "Customer",
        "I am calling from Tala about your overdue loan. This call is being recorded.": "Agent",
    }
    for text, want in checks.items():
        got = by_text.get(text)
        good = got == want
        ok &= good
        print(f"  {'PASS' if good else 'FAIL'} {text!r} -> {got} (want {want})")

    print("\n=== Attribution summary + QA gate ===")
    summary = summarize_attribution(turns)
    print(f"  summary={summary}")
    verified = to_labelled_text(turns)
    qa = validate_collections_audit(verified, {"ptp_detected": False, "summary": ""}, turns)
    no_ptp = qa["verified_facts"]["ptp_detected"] is False
    disp = qa["corrections"].get("disposition")
    print(f"  PASS no PTP: {no_ptp}")
    print(f"  disposition={disp} review_required={qa['review_required']} qa_conf={qa['qa_confidence']}")
    ok &= no_ptp

    print("\n=== Text fallback: uncued line is low confidence ===")
    flip = (
        "Agent: Your loan amount is overdue, please pay.\n"
        "Customer: aap kaise ho.\n"            # neutral chatter, no cue -> should not flip away
        "Agent: When will you pay the amount?\n"
    )
    flip_turns = attribute_transcript(flip)
    for t in flip_turns:
        print(f"  {t['speaker']:8} ({t['confidence']}) {t['text']}  [{t['reason']}]")

    print("\n=== Full pipeline via format_labelled_transcript ===")
    out_turns = []
    text = format_labelled_transcript(raw, out_turns)
    print(text)
    pipeline_ok = len(out_turns) == len(turns) and all("confidence" in t for t in out_turns)
    ok &= pipeline_ok
    print(f"  PASS pipeline emits {len(out_turns)} turns with confidence: {pipeline_ok}")

    print("\n" + ("ALL PASSED" if ok else "SOME TESTS FAILED"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
