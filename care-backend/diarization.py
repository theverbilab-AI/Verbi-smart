"""
Real speaker diarization via Sarvam's Batch Speech-to-Text-Translate API.

ROOT-CAUSE FIX:
The realtime `speech-to-text-translate` endpoint returns plain text with NO
speaker labels, and chunk-merging collapses every turn boundary. Speaker turns
used to be *reconstructed* from that text by LLM + keyword heuristics, which
defaults unlabelled lines to "Agent" via turn continuity — so calls collapsed to
all-Agent. This module instead gets ground-truth speaker segments straight from
the audio (Sarvam batch diarization, `with_diarization=True`) and makes ONE
per-call decision to map each `speaker_id` to Agent / Customer.

If diarization is disabled, unavailable, or fails, `diarize_audio` returns None
and the caller transparently falls back to the legacy text-bifurcation path.
"""
from __future__ import annotations

import glob
import json
import os
import shutil
import tempfile

from speaker_attribution import _AGENT, _CUSTOMER, _PROBING, _hits

# Master switch + tuning (all overridable via env).
CARE_USE_DIARIZATION = os.getenv("CARE_USE_DIARIZATION", "1") == "1"
DIAR_NUM_SPEAKERS = int(os.getenv("CARE_DIAR_NUM_SPEAKERS", "2"))
DIAR_WAIT_TIMEOUT = int(os.getenv("CARE_DIAR_TIMEOUT", "600"))
DIAR_UPLOAD_TIMEOUT = float(os.getenv("CARE_DIAR_UPLOAD_TIMEOUT", "300"))


def _client():
    key = os.getenv("SARVAM_API_KEY")
    if not key:
        print("[DIAR] SARVAM_API_KEY missing — skipping diarization", flush=True)
        return None
    try:
        from sarvamai import SarvamAI

        return SarvamAI(api_subscription_key=key)
    except Exception as exc:  # SDK missing / import error
        print(f"[DIAR] sarvamai SDK unavailable ({exc}) — falling back", flush=True)
        return None


def _merge_entries(entries: list[dict]) -> list[dict]:
    """Collapse consecutive segments from the same speaker_id into single turns."""
    turns: list[dict] = []
    for e in entries:
        sid = str(e.get("speaker_id"))
        text = (e.get("transcript") or "").strip()
        if not text:
            continue
        if turns and turns[-1]["speaker_id"] == sid:
            turns[-1]["text"] = f"{turns[-1]['text']} {text}".strip()
            turns[-1]["end"] = e.get("end_time_seconds")
        else:
            turns.append(
                {
                    "speaker_id": sid,
                    "text": text,
                    "start": e.get("start_time_seconds"),
                    "end": e.get("end_time_seconds"),
                }
            )
    return turns


def _signal(text: str) -> tuple[int, int]:
    """Return (agent_signal, customer_signal) for a block of speaker text."""
    low = (text or "").lower()
    agent = sum(w for w, _ in (_hits(low, _AGENT) + _hits(low, _PROBING)))
    cust = sum(w for w, _ in _hits(low, _CUSTOMER))
    return agent, cust


def _map_speakers(turns: list[dict]) -> dict[str, str]:
    """One per-call decision: which speaker_id is the Agent.

    Agent = the speaker whose aggregated lines carry the strongest agent signal
    (recording disclaimer, "on behalf", loan/EMI references, RPC/probing) net of
    customer signal. Tie / no-signal fallback: whoever speaks first, since the
    collections agent opens the call. This is a *role assignment*, not a per-line
    keyword override — the diarizer already decided who spoke each line.
    """
    agg: dict[str, int] = {}
    first_seen: dict[str, int] = {}
    for i, t in enumerate(turns):
        sid = t["speaker_id"]
        a, c = _signal(t["text"])
        agg[sid] = agg.get(sid, 0) + (a - c)
        first_seen.setdefault(sid, i)

    speakers = sorted(agg.keys(), key=lambda s: first_seen[s])
    if not speakers:
        return {}

    has_signal = any(v != 0 for v in agg.values())
    if has_signal:
        # Highest net agent signal wins; earliest speaker breaks ties.
        agent_id = max(speakers, key=lambda s: (agg[s], -first_seen[s]))
    else:
        agent_id = speakers[0]  # first speaker opens → Agent

    return {s: ("Agent" if s == agent_id else "Customer") for s in speakers}


def diarize_audio(audio_path: str) -> list[dict] | None:
    """Return canonical speaker turns from real audio diarization, or None.

    Each turn: {speaker, text, confidence, reason, original_speaker, changed,
    speaker_id, start, end}. None signals the caller to use the legacy pipeline.
    """
    if not CARE_USE_DIARIZATION:
        return None
    client = _client()
    if client is None:
        return None

    outdir = tempfile.mkdtemp(prefix="care_diar_")
    try:
        kwargs: dict = {"model": "saaras:v3", "with_diarization": True}
        if DIAR_NUM_SPEAKERS > 0:
            kwargs["num_speakers"] = DIAR_NUM_SPEAKERS
        print(f"[DIAR] creating batch diarization job {kwargs}", flush=True)
        try:
            job = client.speech_to_text_translate_job.create_job(**kwargs)
        except Exception:
            # Some SDK builds pin the model literal — retry with the default.
            kwargs.pop("model", None)
            job = client.speech_to_text_translate_job.create_job(**kwargs)

        job.upload_files(file_paths=[audio_path], timeout=DIAR_UPLOAD_TIMEOUT)
        job.start()
        print(f"[DIAR] job {job.job_id} started, waiting...", flush=True)
        job.wait_until_complete(timeout=DIAR_WAIT_TIMEOUT)
        if job.is_failed():
            print(f"[DIAR] job {job.job_id} failed — falling back", flush=True)
            return None

        if not job.download_outputs(output_dir=outdir):
            print("[DIAR] download_outputs returned False — falling back", flush=True)
            return None
        files = glob.glob(os.path.join(outdir, "*.json"))
        if not files:
            print("[DIAR] no output json — falling back", flush=True)
            return None

        with open(files[0], encoding="utf-8") as fh:
            data = json.load(fh)
        diarized = (data or {}).get("diarized_transcript") or {}
        entries = diarized.get("entries") or []
        if not entries:
            print("[DIAR] response had no diarized entries — falling back", flush=True)
            return None

        merged = _merge_entries(entries)
        if not merged:
            return None
        mapping = _map_speakers(merged)

        turns: list[dict] = []
        for t in merged:
            speaker = mapping.get(t["speaker_id"], "Customer")
            turns.append(
                {
                    "speaker": speaker,
                    "text": t["text"],
                    "confidence": 0.92,
                    "reason": f"sarvam diarization (speaker_id={t['speaker_id']} -> {speaker})",
                    "original_speaker": speaker,
                    "changed": False,
                    "speaker_id": t["speaker_id"],
                    "start": t.get("start"),
                    "end": t.get("end"),
                }
            )

        roles = sorted(set(mapping.values()))
        print(
            f"[DIAR] {len(entries)} segments -> {len(turns)} turns | "
            f"speaker_ids={sorted(set(mapping))} -> roles={roles}",
            flush=True,
        )
        return turns
    except Exception as exc:
        print(f"[DIAR] error ({exc}) — falling back to text bifurcation", flush=True)
        return None
    finally:
        shutil.rmtree(outdir, ignore_errors=True)
