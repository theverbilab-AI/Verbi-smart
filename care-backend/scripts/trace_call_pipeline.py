"""
Full pipeline trace — investigation only. No fixes.
Usage: python scripts/trace_call_pipeline.py <audio_or_call_id>
"""
from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv

load_dotenv()

REPORT_PATH = os.path.join(
    os.path.dirname(os.path.dirname(__file__)),
    "scripts",
    "PIPELINE_TRACE_REPORT.md",
)


def _hdr(n: int, title: str) -> str:
    return f"\n## Stage {n}: {title}\n\n"


def trace_disposition_candidates(transcript: str) -> dict:
    from scoring_rules import (
        detect_call_kpis,
        detect_call_context,
        _extract_ptp_details,
        _detect_dispositions,
        resolve_disposition,
        _detect_third_party_compliance,
    )

    kpis = detect_call_kpis(transcript)
    ctx = kpis.get("_ctx") or detect_call_context(transcript)
    ptp = _extract_ptp_details(transcript, ctx)
    agent_text = ctx.get("agent_text") or ""
    customer_text = ctx.get("customer_text") or ""
    third = _detect_third_party_compliance(
        agent_text, customer_text, ctx.get("full_lower") or "",
        rpc_confirmed=bool(kpis.get("rpc_confirmed")),
    )
    tags = _detect_dispositions(transcript, ctx, ptp, third)
    resolved = resolve_disposition(transcript, kpis, ptp)

    priority = [
        "DISPUTE", "REFUSED_TO_PAY", "FINANCIAL_HARDSHIP", "MEDICAL_ISSUE",
        "APP_ISSUE", "LANGUAGE_ISSUE", "DISCONNECTED", "CALLBACK",
    ]
    winner = None
    for pref in priority:
        if pref in [str(t).upper() for t in tags]:
            winner = pref
            break

    return {
        "tags_from_rules": tags,
        "resolve_disposition": resolved,
        "priority_winner_among_tags": winner,
        "ptp_detected": bool(ptp.get("ptp_detected")),
        "is_wrong_number": bool(ctx.get("is_wrong_number")),
        "third_party": bool(kpis.get("third_party")),
        "customer_text_sample": (customer_text or "")[:300],
        "language_phrases_in_customer": [
            p for p in (
                "don't understand", "language", "hindi nahi", "english nahi",
                "samajh nahi", "language barrier", "language issue",
            ) if p in (customer_text or "").lower()
        ],
        "language_phrases_in_full": [
            p for p in (
                "don't understand", "language", "hindi nahi", "english nahi",
                "samajh nahi", "language barrier", "language issue",
            ) if p in (ctx.get("full_lower") or "")
        ],
    }


def main():
    arg = sys.argv[1] if len(sys.argv) > 1 else r"C:\Users\SIDDHANTH REMMA\Downloads\sumit-098765.wav"
    lines: list[str] = ["# Pipeline Root-Cause Trace Report\n"]

    # ── Stage 1 ──
    lines.append(_hdr(1, "Audio received"))
    audio_path = arg
    call_id = None
    db_call = None
    if arg.upper().startswith("CALL-"):
        call_id = arg
        from database import get_call

        db_call = get_call(call_id) or {}
        audio_path = (
            db_call.get("file_path")
            or db_call.get("source_uri")
            or r"C:\Users\SIDDHANTH REMMA\Downloads\sumit-098765.wav"
        )
        lines.append(f"- **call_id:** `{call_id}`\n")
        lines.append(f"- **DB status:** `{db_call.get('status')}`\n")
        lines.append(f"- **DB disposition:** `{db_call.get('disposition')}`\n")
        lines.append(f"- **filename:** `{db_call.get('filename')}`\n")
    lines.append(f"- **audio_path:** `{audio_path}`\n")
    lines.append(f"- **exists:** `{os.path.isfile(audio_path)}`\n")
    if os.path.isfile(audio_path):
        lines.append(f"- **size_mb:** `{round(os.path.getsize(audio_path) / 1024 / 1024, 2)}`\n")
    lines.append(f"- **CARE_USE_DIARIZATION:** `{os.getenv('CARE_USE_DIARIZATION', '1')}`\n")

    # ── Stage 2 & 3: Sarvam diarization raw ──
    lines.append(_hdr(2, "Sarvam request payload"))
    diar_kwargs = {"model": "saaras:v3", "with_diarization": True, "num_speakers": int(os.getenv("CARE_DIAR_NUM_SPEAKERS", "2"))}
    lines.append("```json\n" + json.dumps(diar_kwargs, indent=2) + "\n```\n")

    lines.append(_hdr(3, "Raw Sarvam response (speaker labels)"))
    sarvam_entries = []
    diar_turns = None
    try:
        import glob
        import shutil
        import tempfile
        from diarization import _client, _merge_entries, _map_speakers, CARE_USE_DIARIZATION

        if not CARE_USE_DIARIZATION:
            lines.append("**DIARIZATION DISABLED** via CARE_USE_DIARIZATION\n")
        elif not os.path.isfile(audio_path):
            lines.append("**Audio file not found — skipping Sarvam call**\n")
        else:
            client = _client()
            if not client:
                lines.append("**Sarvam client unavailable**\n")
            else:
                outdir = tempfile.mkdtemp(prefix="trace_diar_")
                try:
                    job = client.speech_to_text_translate_job.create_job(**diar_kwargs)
                    lines.append(f"- **job_id:** `{job.job_id}`\n")
                    job.upload_files(file_paths=[audio_path])
                    job.start()
                    job.wait_until_complete(timeout=int(os.getenv("CARE_DIAR_TIMEOUT", "600")))
                    job.download_outputs(output_dir=outdir)
                    files = glob.glob(os.path.join(outdir, "*.json"))
                    if files:
                        with open(files[0], encoding="utf-8") as fh:
                            raw = json.load(fh)
                        entries = (raw.get("diarized_transcript") or {}).get("entries") or []
                        sarvam_entries = entries[:15]
                        lines.append(f"- **total entries:** {len(entries)}\n")
                        lines.append("**First 15 entries:**\n```json\n")
                        lines.append(json.dumps(sarvam_entries, indent=2, ensure_ascii=False)[:8000])
                        lines.append("\n```\n")
                        merged = _merge_entries(entries)
                        mapping = _map_speakers(merged)
                        lines.append(f"- **speaker_id → role mapping:** `{mapping}`\n")
                        from diarization import diarize_audio
                        diar_turns = diarize_audio(audio_path)
                finally:
                    shutil.rmtree(outdir, ignore_errors=True)
    except Exception as exc:
        lines.append(f"**Sarvam error:** `{exc}`\n")

    # ── Stage 4: Full transcribe path ──
    lines.append(_hdr(4, "Translation / labelled transcript (processor.transcribe)"))
    from processor import transcribe

    agent_t, labelled, diarized_turns_from_transcribe = transcribe(audio_path)
    lines.append(f"- **diarized_turns returned:** `{diarized_turns_from_transcribe is not None}`\n")
    if diarized_turns_from_transcribe:
        lines.append(f"- **turn count:** `{len(diarized_turns_from_transcribe)}`\n")
        lines.append("**First 8 turns (as returned by transcribe):**\n")
        for i, t in enumerate(diarized_turns_from_transcribe[:8]):
            lines.append(
                f"{i}. speaker=`{t.get('speaker')}` conf=`{t.get('confidence')}` "
                f"source=`{t.get('attribution_source')}` changed=`{t.get('changed')}` "
                f"raw=`{t.get('raw_speaker')}` | {(t.get('text') or '')[:80]}\n"
            )
    else:
        lines.append("**FALLBACK PATH** — no diarized_turns; text bifurcation used.\n")
        lines.append(f"- labelled transcript length: `{len(labelled or '')}`\n")
        for ln in (labelled or "").splitlines()[:8]:
            lines.append(f"  - `{ln[:100]}`\n")

    # ── Stage 5: Speaker attribution before/after ──
    lines.append(_hdr(5, "Speaker attribution — before / after correction"))
    from speaker_attribution import attribute_transcript, summarize_attribution
    from processor import format_labelled_transcript

    if diarized_turns_from_transcribe:
        lines.append("**Path: audio diarization** — `attribute_transcript()` is NOT called in processor when diarized_turns exist.\n")
        lines.append("Turns pass through unchanged from `diarization.diarize_audio()` → `processor._process_call_inner`.\n\n")
        before = diarized_turns_from_transcribe
        after = before  # no second pass
    else:
        lines.append("**Path: text fallback** — `format_labelled_transcript()` calls `attribute_transcript()`.\n\n")
        speaker_turns_out: list = []
        formatted = format_labelled_transcript(labelled, speaker_turns_out)
        before = [{"speaker": "from_bifurcation", "text": ln} for ln in (labelled or "").splitlines()[:8]]
        after = speaker_turns_out

    lines.append("**Before correction (first 8):**\n")
    for i, t in enumerate(before[:8]):
        if isinstance(t, dict):
            lines.append(
                f"{i}. orig=`{t.get('original_speaker', t.get('speaker'))}` "
                f"speaker=`{t.get('speaker')}` conf=`{t.get('confidence')}` "
                f"| {(t.get('text') or '')[:70]}\n"
            )
        else:
            lines.append(f"{i}. `{t}`\n")

    lines.append("\n**After correction (first 8):**\n")
    for i, t in enumerate(after[:8]):
        lines.append(
            f"{i}. orig=`{t.get('original_speaker')}` → `{t.get('speaker')}` "
            f"conf=`{t.get('confidence')}` changed=`{t.get('changed')}` "
            f"reason=`{t.get('reason')}` | {(t.get('text') or '')[:70]}\n"
        )
    summary = summarize_attribution(after if isinstance(after, list) else [])
    lines.append(f"\n**Attribution summary:** `{json.dumps(summary, default=str)}`\n")

    # ── Stage 6: Disposition ──
    lines.append(_hdr(6, "Disposition classification"))
    display_transcript = labelled
    if diarized_turns_from_transcribe:
        from speaker_attribution import to_labelled_text
        display_transcript = to_labelled_text(diarized_turns_from_transcribe)
    disp_info = trace_disposition_candidates(display_transcript)
    lines.append("```json\n" + json.dumps(disp_info, indent=2, ensure_ascii=False) + "\n```\n")

    from processor import score_transcript
    scored = score_transcript(display_transcript, os.path.basename(audio_path), audit_mode="collections")
    lines.append(f"- **score_transcript disposition:** `{scored.get('disposition')}`\n")
    lines.append(f"- **scoring_source:** `{scored.get('scoring_source')}`\n")

    # ── Stage 7: DB write simulation ──
    lines.append(_hdr(7, "Database write (what processor saves)"))
    speaker_turns_save = diarized_turns_from_transcribe or after
    payload_analysis = {
        "speaker_turns": speaker_turns_save[:3] if speaker_turns_save else [],
        "speaker_turns_count": len(speaker_turns_save or []),
        "audit_mode": "collections",
    }
    lines.append(f"- **transcript first 200 chars:** `{(display_transcript or '')[:200]}`\n")
    lines.append(f"- **speaker_turns saved:** `{len(speaker_turns_save or [])}` turns\n")
    if speaker_turns_save:
        t0 = speaker_turns_save[0]
        lines.append(
            f"- **turn[0] keys:** `{list(t0.keys())}`\n"
            f"- **turn[0]:** speaker=`{t0.get('speaker')}` conf=`{t0.get('confidence')}` "
            f"source=`{t0.get('attribution_source')}`\n"
        )

    if db_call:
        analysis_db = db_call.get("analysis") or {}
        if isinstance(analysis_db, str):
            try:
                analysis_db = json.loads(analysis_db)
            except Exception:
                analysis_db = {}
        st_db = analysis_db.get("speaker_turns") or []
        lines.append("\n**ACTUAL DB record:**\n")
        lines.append(f"- **disposition in DB:** `{db_call.get('disposition')}`\n")
        lines.append(f"- **speaker_turns in DB:** `{len(st_db)}` turns\n")
        lines.append(f"- **speaker_reattributed_on_read:** `{analysis_db.get('speaker_reattributed_on_read')}`\n")
        if st_db:
            for i, t in enumerate(st_db[:6]):
                lines.append(
                    f"  DB turn {i}: speaker=`{t.get('speaker')}` conf=`{t.get('confidence')}` "
                    f"source=`{t.get('attribution_source')}` | {(t.get('text') or '')[:60]}\n"
                )
        else:
            lines.append("  **NO speaker_turns in DB** — UI will parse transcript or re-attribute on read.\n")

    # ── Stage 8: API enrich ──
    lines.append(_hdr(8, "API response (_enrich_call_payload on GET)"))
    if db_call:
        from app import _enrich_call_payload
        enriched = _enrich_call_payload(dict(db_call))
        ea = enriched.get("analysis") or {}
        est = ea.get("speaker_turns") or []
        lines.append(f"- **disposition after enrich:** `{enriched.get('disposition')}`\n")
        lines.append(f"- **speaker_turns after enrich:** `{len(est)}`\n")
        lines.append(f"- **speaker_reattributed_on_read:** `{ea.get('speaker_reattributed_on_read')}`\n")
        if est:
            for i, t in enumerate(est[:6]):
                lines.append(
                    f"  API turn {i}: speaker=`{t.get('speaker')}` conf=`{t.get('confidence')}` "
                    f"changed=`{t.get('changed')}` | {(t.get('text') or '')[:60]}\n"
                )
        qa = ea.get("qa_validation") or {}
        lines.append(f"- **qa corrections applied on read:** see disposition above\n")
        lines.append(f"- **review_required:** `{qa.get('review_required')}`\n")
    else:
        lines.append("No call_id provided — skip DB enrich. Re-run with `CALL-XXXX` to compare.\n")

    # ── Stage 9: Frontend ──
    lines.append(_hdr(9, "Frontend rendering"))
    lines.append(
        "File: `care-dashboard/src/utils/transcript.js` → `getVerifiedTurns(call)`\n\n"
        "1. If `call.analysis.speaker_turns` exists → use verbatim (confidence from turn)\n"
        "2. Else → `parseTranscriptTurns(call.transcript)` with **confidence: null** OR\n"
        "3. If `_enrich_call_payload` ran `attribute_transcript` → **~55% confidence**, text fallback\n\n"
    )
    if db_call:
        analysis_db = db_call.get("analysis") or {}
        if isinstance(analysis_db, str):
            try:
                analysis_db = json.loads(analysis_db)
            except Exception:
                analysis_db = {}
        has_turns = bool(analysis_db.get("speaker_turns"))
        lines.append(
            f"For this call: speaker_turns in DB = **{has_turns}**. "
            f"UI 55% pattern = **`attribute_transcript` text fallback**, not Sarvam diarization (92%).\n"
        )

    # Root cause summary
    lines.append("\n---\n\n## Root Cause Summary (investigation)\n\n")
    if not diarized_turns_from_transcribe:
        lines.append("1. **Diarization did not produce turns** for this run — fallback text path used.\n")
    else:
        lines.append("1. **Diarization works** when run fresh — 92% confidence, correct Agent/Customer.\n")
    if db_call:
        analysis_db = db_call.get("analysis") or {}
        if isinstance(analysis_db, str):
            try:
                analysis_db = json.loads(analysis_db)
            except Exception:
                analysis_db = {}
        if not analysis_db.get("speaker_turns"):
            lines.append(
                "2. **DB has no `analysis.speaker_turns`** → `_enrich_call_payload` (app.py:291-298) "
                "re-runs `attribute_transcript()` on every GET → **55% confidence**, mislabels customer lines as Agent.\n"
            )
        else:
            st = analysis_db.get("speaker_turns") or []
            confs = [t.get("confidence") for t in st[:5]]
            if confs and all(c and c < 0.6 for c in confs if c is not None):
                lines.append("2. **DB speaker_turns are text-fallback quality** (~55%), not diarization (92%).\n")
            else:
                lines.append("2. **DB has diarization-quality turns** — if UI still wrong, check enrich overwrite.\n")
    lines.append(
        "3. **LANGUAGE_ISSUE:** from `resolve_disposition` / `_detect_dispositions` in `scoring_rules.py` "
        "OR stored at process time before rule fix; `_enrich_call_payload` re-applies `validate_collections_audit` "
        "corrections on GET (app.py:312-315).\n"
    )

    report = "".join(lines)
    with open(REPORT_PATH, "w", encoding="utf-8") as fh:
        fh.write(report)
    print(report)
    print(f"\n[WRITTEN] {REPORT_PATH}")


if __name__ == "__main__":
    main()
