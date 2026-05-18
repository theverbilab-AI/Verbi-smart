"""
CARE Processing Pipeline v10 - PRD aligned, PostgreSQL safe

Upgrades:
- Speaker-labelled transcript cleanup: Agent / Customer turns
- Agent + loan metadata extraction from filename pattern: Agent_123456.wav
- PRD scoring prompt with third-party/RPC disclosure handling
- Disposition, AI detection, AI suggestion, risk level, confidence fields
- Safer PostgreSQL updates: retries when optional columns are not present yet
- S3/Drive/direct URL ingestion retained
"""

import os, json, re, threading, tempfile, shutil, subprocess
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from urllib.parse import urlparse, unquote
import requests

CHUNK_SECONDS = int(os.getenv("CARE_CHUNK_SECONDS", "25"))
AUDIO_EXTS = (".mp3", ".wav", ".m4a", ".ogg", ".flac", ".aac", ".wma")
OPTIONAL_RESULT_FIELDS = {
    "ai_detection", "ai_suggestion", "risk_level", "disposition", "confidence",
    "agent_transcript", "transcript", "scores_breakdown", "compliance_flags",
    "key_issues", "strengths", "ptp_amount", "ptp_date", "ptp_mode",
    "agent_sentiment", "sentiment_notes", "summary", "coaching_tip",
    "critical_fail", "ptp_detected", "processed_at", "agent_id", "loan_id",
}


def _safe_update_call(update_call_fn, call_id, payload):
    """Call update_call_fn but do not let missing optional DB columns kill processing."""
    clean = _db_fields(dict(payload))
    while True:
        try:
            return update_call_fn(call_id, clean)
        except Exception as exc:
            msg = str(exc)
            m = re.search(r'column "([^"]+)" .*does not exist', msg, flags=re.I)
            if m and m.group(1) in clean:
                missing = m.group(1)
                print(f"[DB] Optional column missing, skipping field: {missing}", flush=True)
                clean.pop(missing, None)
                continue
            raise


def _bool(v):
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float)):
        return bool(v)
    if isinstance(v, str):
        return v.strip().lower() in {"1", "true", "yes", "y", "detected"}
    return False


def _int_bool(v):
    return 1 if _bool(v) else 0


def _db_fields(payload: dict) -> dict:
    """Ensure lists/dicts/bools are safe for PostgreSQL before update_call."""
    try:
        from database import clean_fields
        return clean_fields(payload)
    except Exception:
        out = {}
        for k, v in payload.items():
            if isinstance(v, (list, dict)):
                out[k] = json.dumps(v, ensure_ascii=False)
            else:
                out[k] = v
        return out


def _as_list(v):
    if v is None:
        return []
    if isinstance(v, list):
        return [str(x) for x in v if str(x).strip()]
    if isinstance(v, str):
        return [x.strip() for x in re.split(r"[,;|]", v) if x.strip()]
    return [str(v)]


def parse_filename_metadata(filename):
    """Extract agent_id and loan_id from Sid_123456.wav style filenames."""
    base = os.path.basename(str(filename or ""))
    base = unquote(base.split("?", 1)[0])
    name, _ext = os.path.splitext(base)
    name = name.strip()

    # Common final filename can contain CALL-ID_originalfilename.
    if "_" in name:
        parts = [p.strip() for p in name.split("_") if p.strip()]
        if len(parts) >= 2:
            agent = parts[0]
            loan = parts[1]
            # If filename starts with CALL-XXXX_Sid_123456, prefer Sid_123456.
            if agent.upper().startswith("CALL-") and len(parts) >= 3:
                agent, loan = parts[1], parts[2]
            return {"agent_id": agent or "Unknown", "loan_id": loan or name}

    m = re.match(r"([A-Za-z][A-Za-z0-9.-]*)[- ]+(\d{4,})", name)
    if m:
        return {"agent_id": m.group(1), "loan_id": m.group(2)}

    return {"agent_id": "Unknown", "loan_id": name or "Unknown"}


def fetch_from_google_drive(url, dest_dir):
    file_id = None
    m = re.search(r"/file/d/([a-zA-Z0-9_-]+)", url)
    if m:
        file_id = m.group(1)
    else:
        m = re.search(r"[?&]id=([a-zA-Z0-9_-]+)", url)
        if m:
            file_id = m.group(1)
    if not file_id:
        file_id = url.strip().split("?")[0].split("/")[-1]

    print(f"[GDRIVE] File ID: {file_id}", flush=True)
    dl = f"https://drive.google.com/uc?export=download&id={file_id}"
    s = requests.Session()
    s.headers.update({"User-Agent": "Mozilla/5.0"})
    r = s.get(dl, stream=True, timeout=120)

    # Large public files can require a confirmation token.
    token = None
    for k, v in r.cookies.items():
        if "download_warning" in k or "confirm" in k.lower():
            token = v
            break
    if token:
        r = s.get(dl + "&confirm=" + token, stream=True, timeout=120)

    dest = os.path.join(dest_dir, f"gdrive_{file_id}.mp3")
    total = 0
    with open(dest, "wb") as f:
        for chunk in r.iter_content(32768):
            if chunk:
                f.write(chunk)
                total += len(chunk)

    if total < 1000:
        raise RuntimeError(
            f"Google Drive download failed — only {total} bytes. "
            "Make sure file is shared as 'Anyone with link can view'."
        )
    print(f"[GDRIVE] Done {total // 1024}KB", flush=True)
    return dest


def fetch_from_url(url, dest_dir):
    parsed = urlparse(url)
    fname = os.path.basename(unquote(parsed.path)) or "audio.mp3"
    if not fname.lower().endswith(AUDIO_EXTS):
        fname += ".mp3"
    dest = os.path.join(dest_dir, fname)
    print(f"[URL] Downloading {url}", flush=True)

    r = requests.get(url, stream=True, timeout=120, headers={"User-Agent": "CARE/1.0"})
    r.raise_for_status()
    with open(dest, "wb") as f:
        for chunk in r.iter_content(32768):
            if chunk:
                f.write(chunk)

    if os.path.getsize(dest) < 1000:
        raise RuntimeError("Downloaded file is too small; check URL permissions/content type.")
    print(f"[URL] Done {os.path.getsize(dest) // 1024}KB", flush=True)
    return dest


def fetch_from_s3(s3_uri, dest_dir):
    try:
        import boto3
        from botocore.exceptions import ClientError
    except ImportError:
        raise ImportError("Run: pip install boto3")

    uri = s3_uri.replace("s3://", "", 1)
    bucket, key = uri.split("/", 1)
    dest = os.path.join(dest_dir, os.path.basename(key) or "audio.mp3")
    print(f"[S3] Downloading s3://{bucket}/{key}", flush=True)

    client = boto3.client(
        "s3",
        region_name=os.getenv("AWS_REGION", "eu-north-1"),
        aws_access_key_id=os.getenv("AWS_ACCESS_KEY_ID"),
        aws_secret_access_key=os.getenv("AWS_SECRET_ACCESS_KEY"),
    )
    try:
        client.download_file(bucket, key, dest)
    except ClientError as exc:
        code = exc.response.get("Error", {}).get("Code")
        if code in {"403", "AccessDenied"}:
            raise RuntimeError(
                "S3 403 Forbidden. Check AWS_ACCESS_KEY_ID/AWS_SECRET_ACCESS_KEY, bucket region, "
                "and IAM policy for s3:GetObject on this bucket/key."
            ) from exc
        raise

    print(f"[S3] Done {os.path.getsize(dest) // 1024}KB", flush=True)
    return dest


def resolve_audio_source(source, dest_dir):
    source = str(source or "").strip()
    if source.startswith("s3://"):
        return fetch_from_s3(source, dest_dir)
    if "drive.google.com" in source:
        return fetch_from_google_drive(source, dest_dir)
    if source.startswith(("http://", "https://")):
        return fetch_from_url(source, dest_dir)
    return source


def _ffmpeg_bin():
    """Resolve ffmpeg binary (Docker/Railway: apt install ffmpeg or set FFMPEG_PATH)."""
    custom = os.getenv("FFMPEG_PATH", "").strip()
    if custom and os.path.isfile(custom):
        return custom
    found = shutil.which("ffmpeg")
    if found:
        return found
    for path in ("/usr/bin/ffmpeg", "/usr/local/bin/ffmpeg"):
        if os.path.isfile(path):
            return path
    return None


def split_audio(path, chunk_sec=CHUNK_SECONDS):
    ffmpeg = _ffmpeg_bin()
    if not ffmpeg:
        print("[CHUNK] ffmpeg not found — transcribing full file (no chunking)", flush=True)
        return [path], None

    tmpdir = tempfile.mkdtemp(prefix="care_chunks_")
    pattern = os.path.join(tmpdir, "chunk_%04d.mp3")
    try:
        r = subprocess.run(
            [
                ffmpeg, "-hide_banner", "-loglevel", "error",
                "-i", path,
                "-f", "segment",
                "-segment_time", str(chunk_sec),
                "-c:a", "libmp3lame",
                "-q:a", "4",
                "-y", pattern,
            ],
            capture_output=True,
            text=True,
        )
    except FileNotFoundError:
        print("[CHUNK] ffmpeg missing — transcribing full file (no chunking)", flush=True)
        shutil.rmtree(tmpdir, ignore_errors=True)
        return [path], None
    if r.returncode != 0:
        print("[CHUNK] ffmpeg failed — single file mode", flush=True)
        print((r.stderr or "")[:500], flush=True)
        shutil.rmtree(tmpdir, ignore_errors=True)
        return [path], None

    chunks = sorted(os.path.join(tmpdir, f) for f in os.listdir(tmpdir) if f.startswith("chunk_"))
    if not chunks:
        shutil.rmtree(tmpdir, ignore_errors=True)
        return [path], None
    print(f"[CHUNK] {len(chunks)} chunks of {chunk_sec}s", flush=True)
    return chunks, tmpdir


def _transcribe_chunk(chunk_path, api_key, idx):
    with open(chunk_path, "rb") as f:
        data = f.read()
    r = requests.post(
        "https://api.sarvam.ai/speech-to-text-translate",
        headers={"api-subscription-key": api_key},
        files={"file": (os.path.basename(chunk_path), data, "audio/mpeg")},
        data={
            "model": "saaras:v3",
            "language_code": "unknown",
            "target_language_code": "en-IN",
        },
        timeout=60,
    )
    if r.status_code != 200:
        print(f"[CHUNK {idx}] Error {r.status_code}: {r.text[:200]}", flush=True)
        return idx, ""
    text = r.json().get("transcript", "").strip()
    print(f"[CHUNK {idx}] {len(text)} chars", flush=True)
    return idx, text


def _heuristic_bifurcate(text):
    """Fallback when LLM diarisation fails. Keeps transcript readable and avoids blank agent text."""
    text = re.sub(r"\s+", " ", text or "").strip()
    if not text:
        return "", ""
    sentences = re.split(r"(?<=[.!?])\s+", text)
    turns = []
    speaker = "Agent"
    customer_cues = re.compile(r"\b(i don'?t|i have|my job|can you|hello\??|i will|unable|problem|issue|lost my|money)\b", re.I)
    agent_cues = re.compile(r"\b(company|bank|loan|emi|payment|outstanding|overdue|calling|pay|amount|due|sir|madam)\b", re.I)
    for sent in sentences:
        sent = sent.strip()
        if not sent:
            continue
        if customer_cues.search(sent) and not agent_cues.search(sent[:80]):
            speaker = "Customer"
        elif agent_cues.search(sent):
            speaker = "Agent"
        turns.append(f"{speaker}: {sent}")
        speaker = "Customer" if speaker == "Agent" else "Agent"
    labelled = "\n".join(turns)
    agent = "\n".join(line for line in turns if line.startswith("Agent:")) or text
    return agent, labelled


def _diarize_with_llm(raw_transcript, api_key):
    """Use the chat model to convert raw ASR text into Agent/Customer turns."""
    if not raw_transcript.strip():
        return "", ""
    prompt = f"""
Convert this collections call transcript into speaker turns.
Use ONLY labels `Agent:` and `Customer:`.
Do not summarize. Preserve all important words, payment amounts, dates, loan details, objections, and disclosures.
If unsure, infer from context. Output only the labelled transcript.

RAW TRANSCRIPT:
{raw_transcript[:9000]}
""".strip()
    r = requests.post(
        "https://api.sarvam.ai/v1/chat/completions",
        headers={"Authorization": "Bearer " + api_key, "Content-Type": "application/json"},
        json={
            "model": os.getenv("SARVAM_CHAT_MODEL", "sarvam-m"),
            "messages": [
                {"role": "system", "content": "You label call transcripts. Output only Agent:/Customer: turns."},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.0,
            "max_tokens": 1800,
        },
        timeout=90,
    )
    if r.status_code != 200:
        raise RuntimeError(f"Diarization LLM {r.status_code}: {r.text[:200]}")
    labelled = r.json()["choices"][0]["message"]["content"].strip()
    labelled = re.sub(r"```.*?\n|```", "", labelled, flags=re.S).strip()
    if "Agent:" not in labelled and "Customer:" not in labelled:
        raise ValueError("LLM did not return speaker labels")
    agent = "\n".join(line.strip() for line in labelled.splitlines() if line.strip().lower().startswith("agent:"))
    return agent or labelled, labelled


def transcribe(audio_path):
    key = os.getenv("SARVAM_API_KEY")
    if not key:
        raise EnvironmentError("SARVAM_API_KEY not set")

    mb = os.path.getsize(audio_path) / 1024 / 1024
    print(f"[STT] {os.path.basename(audio_path)} ({round(mb, 1)} MB)", flush=True)
    chunks, tmpdir = split_audio(audio_path)
    try:
        if len(chunks) == 1:
            _, raw_text = _transcribe_chunk(chunks[0], key, 0)
        else:
            results = {}
            with ThreadPoolExecutor(max_workers=min(8, len(chunks))) as ex:
                futs = {ex.submit(_transcribe_chunk, c, i and key or key, i): i for i, c in enumerate(chunks)}
                for f in as_completed(futs):
                    i, t = f.result()
                    results[i] = t
            raw_text = " ".join(results[i] for i in sorted(results))
        raw_text = re.sub(r"\s+", " ", raw_text or "").strip()
        print(f"[STT] Raw done {len(raw_text)} chars", flush=True)

        try:
            agent_transcript, labelled = _diarize_with_llm(raw_text, key)
            print(f"[BIFURCATION] LLM labelled. Full: {len(labelled)} | Agent: {len(agent_transcript)}", flush=True)
            return agent_transcript, labelled
        except Exception as exc:
            print(f"[BIFURCATION] LLM failed, using heuristic: {exc}", flush=True)
            return _heuristic_bifurcate(raw_text)
    finally:
        if tmpdir:
            shutil.rmtree(tmpdir, ignore_errors=True)


SCORING_PROMPT = """You are a strict but fair QA auditor for an Indian collections call centre.
Score ONLY the AGENT using the labelled transcript. Output ONLY raw JSON starting with {{. No thinking.

IMPORTANT COMPLIANCE RULES:
1. Right Party Contact / RPC must happen before disclosing loan amount, overdue, EMI, legal/payment details.
2. If a third party answers, the agent should NOT disclose loan details. Agent should request borrower callback.
   - If agent protects privacy and asks callback: Professionalism can be full.
   - If agent discloses loan/payment/overdue/legal details to third party: A7_professionalism = 0 and flag WRONG_DISCLOSURE.
3. Do not mark score zero just because third party answered. Score agent behaviour.
4. PTP must include clear amount + date/time + payment mode/intent. Otherwise use callback/payment issue/etc.
5. Capture customer issues such as financial hardship, app not working, language issue, dispute, disconnected.

FRAMEWORK (20 pts total):
A1 Opening (0-2): disclaimer + company/bank name + customer name + RPC in correct order
A2 Case Knowledge (0-2): exact amount + DPD/overdue days + loan details stated accurately after RPC
A3 Probing (0-3) CRITICAL: asks reason for non-payment and follow-up questions
A4 Negotiation (0-3) CRITICAL: urgency + consequences + part-payment/settlement options
A5 Commitment/PTP (0-3) CRITICAL: amount + date + mode confirmed, or valid callback if borrower unavailable
A6 Closing (0-2): summarizes next action/payment/callback and closes professionally
A7 Professionalism (0-3) CRITICAL: no threat/abuse/sarcasm; empathy; privacy compliant
A8 Call Handling (0-1): controls flow and avoids drift
A9 Troubleshooting (0-1): resolves payment/app/link/technical issues or offers alternative modes

Allowed dispositions:
PTP, CALLBACK, DISCONNECTED, PAYMENT_ISSUE, LANGUAGE_ISSUE, APP_NOT_WORKING, FINANCIAL_HARDSHIP, DISPUTE, THIRD_PARTY, WRONG_NUMBER, NO_RESPONSE, OTHER

Allowed compliance flags:
THREAT, ABUSE, FALSE_PROMISE, WRONG_DISCLOSURE, RPC_MISSED, PTP_DETECTED, NO_PTP, THIRD_PARTY_SAFE, THIRD_PARTY_BREACH, NONE

LABELLED TRANSCRIPT:
{transcript}

Return this exact JSON shape:
{{
  "scores": {{
    "A1_opening": 0,
    "A2_case_knowledge": 0,
    "A3_probing": 0,
    "A4_negotiation": 0,
    "A5_commitment_ptp": 0,
    "A6_closing": 0,
    "A7_professionalism": 0,
    "A8_call_handling": 0,
    "A9_troubleshooting": 0
  }},
  "total_score": 0,
  "total_score_pct": 0,
  "grade": "Poor",
  "critical_fail": false,
  "ptp_detected": false,
  "ptp_amount": null,
  "ptp_date": null,
  "ptp_mode": null,
  "disposition": "OTHER",
  "risk_level": "LOW",
  "ai_detection": ["NONE"],
  "ai_suggestion": "One specific next-best action for agent or QA.",
  "agent_sentiment": "neutral",
  "sentiment_notes": "brief note",
  "compliance_flags": ["NONE"],
  "confidence": 80,
  "summary": "2-3 sentence call summary",
  "key_issues": ["issue1"],
  "strengths": ["strength1"],
  "coaching_tip": "one specific coaching tip"
}}"""


def _clean_json(raw):
    if not raw:
        return ""
    text = raw.strip()
    text = re.sub(r"```json", "", text, flags=re.I)
    text = re.sub(r"```", "", text)
    text = re.sub(r"<think>[\s\S]*?</think>", "", text, flags=re.I)
    match = re.search(r"\{[\s\S]*\}", text)
    if not match:
        return ""
    js = match.group(0)
    js = re.sub(r",(\s*[}\]])", r"\1", js)
    return js.strip()


def _is_valid_json(text):
    try:
        json.loads(text)
        return True
    except Exception:
        return False


def _fallback_score(transcript):
    lower = transcript.lower()
    flags = []
    disposition = "OTHER"
    detections = []

    if any(x in lower for x in ["lost my job", "no job", "financial problem", "no money", "unable to pay", "hardship"]):
        disposition = "FINANCIAL_HARDSHIP"
        detections.append("Financial Hardship Detected")
    if any(x in lower for x in ["app not working", "link not working", "payment app", "upi not working"]):
        disposition = "APP_NOT_WORKING"
        detections.append("Payment/App Issue Detected")
    if any(x in lower for x in ["call later", "callback", "call back"]):
        disposition = "CALLBACK"
    if any(x in lower for x in ["promise", "i will pay", "pay tomorrow", "pay today", "ptp"]):
        disposition = "PTP"
        flags.append("PTP_DETECTED")
    if any(x in lower for x in ["mother", "brother", "sister", "father", "third party"]):
        disposition = "THIRD_PARTY"
        detections.append("Third Party Interaction")
        if any(x in lower for x in ["loan amount", "outstanding", "emi", "overdue", "legal"]):
            flags.append("WRONG_DISCLOSURE")

    scores = {
        "A1_opening": 1,
        "A2_case_knowledge": 1 if any(x in lower for x in ["amount", "outstanding", "emi", "overdue"]) else 0,
        "A3_probing": 1 if any(x in lower for x in ["why", "reason", "problem", "issue"]) else 0,
        "A4_negotiation": 1 if any(x in lower for x in ["pay", "settle", "part payment", "today", "tomorrow"]) else 0,
        "A5_commitment_ptp": 2 if disposition == "PTP" else 0,
        "A6_closing": 1 if any(x in lower for x in ["thank", "callback", "call back", "confirm"]) else 0,
        "A7_professionalism": 0 if "WRONG_DISCLOSURE" in flags else 2,
        "A8_call_handling": 1,
        "A9_troubleshooting": 1 if disposition in {"APP_NOT_WORKING", "PAYMENT_ISSUE"} else 0,
    }
    total = sum(scores.values())
    return {
        "scores": scores,
        "total_score": total,
        "total_score_pct": round(total / 20 * 100),
        "grade": "Good" if total >= 14 else "Needs Improvement" if total >= 8 else "Poor",
        "critical_fail": any(scores[k] == 0 for k in ["A3_probing", "A4_negotiation", "A5_commitment_ptp", "A7_professionalism"]),
        "ptp_detected": "PTP_DETECTED" in flags,
        "ptp_amount": None,
        "ptp_date": None,
        "ptp_mode": None,
        "disposition": disposition,
        "risk_level": "HIGH" if "WRONG_DISCLOSURE" in flags else "MEDIUM" if detections else "LOW",
        "ai_detection": detections or ["NONE"],
        "ai_suggestion": "Review the call for exact score calibration and coach agent on missing parameters.",
        "agent_sentiment": "neutral",
        "sentiment_notes": "Fallback keyword scoring used.",
        "compliance_flags": flags or ["NONE"],
        "confidence": 45,
        "summary": "Fallback scoring generated because model JSON was unavailable.",
        "key_issues": ["Needs manual QA review"],
        "strengths": [],
        "coaching_tip": "Ensure RPC before disclosure and capture amount, date, and mode for PTP.",
    }


def score_transcript(labelled_transcript):
    key = os.getenv("SARVAM_API_KEY")
    if not key:
        raise EnvironmentError("SARVAM_API_KEY not set")
    prompt = SCORING_PROMPT.format(transcript=labelled_transcript[:10000])

    def call_llm(messages, temp=0.0, max_tokens=1400):
        r = requests.post(
            "https://api.sarvam.ai/v1/chat/completions",
            headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"},
            json={
                "model": os.getenv("SARVAM_CHAT_MODEL", "sarvam-m"),
                "messages": messages,
                "temperature": temp,
                "max_tokens": max_tokens,
            },
            timeout=90,
        )
        if r.status_code != 200:
            raise RuntimeError(f"Sarvam LLM {r.status_code}: {r.text}")
        return r.json()["choices"][0]["message"]["content"]

    raw = ""
    try:
        raw = call_llm([
            {"role": "system", "content": "Output ONLY valid raw JSON. Start with { immediately."},
            {"role": "user", "content": prompt},
        ])
        print(f"[SCORE] Attempt 1 ({len(raw)} chars): {raw[:80]}", flush=True)
        js = _clean_json(raw)
        if not js or not _is_valid_json(js):
            raw2 = call_llm([
                {"role": "system", "content": "Return ONLY the corrected JSON object. No markdown."},
                {"role": "user", "content": prompt},
                {"role": "assistant", "content": raw},
                {"role": "user", "content": "Fix and output only valid JSON now."},
            ])
            print(f"[SCORE] Attempt 2 ({len(raw2)} chars): {raw2[:80]}", flush=True)
            js = _clean_json(raw2)
        if not js or not _is_valid_json(js):
            print("[SCORE] JSON failed, using fallback scoring", flush=True)
            result = _fallback_score(labelled_transcript)
        else:
            result = json.loads(js)
    except Exception as exc:
        print(f"[SCORE] LLM failed, using fallback: {exc}", flush=True)
        result = _fallback_score(labelled_transcript)

    scores = result.get("scores") or {}
    # Clamp scores safely.
    max_scores = {
        "A1_opening": 2, "A2_case_knowledge": 2, "A3_probing": 3,
        "A4_negotiation": 3, "A5_commitment_ptp": 3, "A6_closing": 2,
        "A7_professionalism": 3, "A8_call_handling": 1, "A9_troubleshooting": 1,
    }
    fixed_scores = {}
    for k, mx in max_scores.items():
        try:
            val = int(scores.get(k, 0) or 0)
        except Exception:
            val = 0
        fixed_scores[k] = max(0, min(mx, val))
    result["scores"] = fixed_scores

    total = sum(fixed_scores.values())
    result["total_score"] = total
    result["total_score_pct"] = int(round((total / 20) * 100))
    result["grade"] = "Excellent" if total >= 18 else "Good" if total >= 14 else "Needs Improvement" if total >= 8 else "Poor"

    critical = ["A3_probing", "A4_negotiation", "A5_commitment_ptp", "A7_professionalism"]
    result["critical_fail"] = bool(any(fixed_scores.get(k, 0) == 0 for k in critical))
    result["ptp_detected"] = _bool(result.get("ptp_detected"))
    result["compliance_flags"] = [f for f in _as_list(result.get("compliance_flags")) if f != "NONE"] or []
    result["ai_detection"] = _as_list(result.get("ai_detection")) or ["NONE"]
    result["key_issues"] = _as_list(result.get("key_issues"))
    result["strengths"] = _as_list(result.get("strengths"))
    result["disposition"] = str(result.get("disposition") or "OTHER").upper().replace(" ", "_")
    result["risk_level"] = str(result.get("risk_level") or "LOW").upper()
    try:
        result["confidence"] = int(result.get("confidence") or 80)
    except Exception:
        result["confidence"] = 80

    print(f"[SCORE] Done {total}/20 ({result['grade']}) | {result['disposition']}", flush=True)
    return result


def process_call(call_id, audio_source, calls_db, update_call_fn):
    tmp = tempfile.mkdtemp(prefix="care_dl_")
    try:
        if not os.path.isfile(str(audio_source)):
            _safe_update_call(update_call_fn, call_id, {"status": "fetching"})
            local = resolve_audio_source(audio_source, tmp)
        else:
            local = audio_source

        metadata = parse_filename_metadata(local)
        _safe_update_call(update_call_fn, call_id, {"status": "transcribing", **metadata})
        print(f"[PIPELINE] {call_id} transcribing... metadata={metadata}", flush=True)

        agent_transcript, labelled_transcript = transcribe(local)
        if not labelled_transcript.strip():
            _safe_update_call(update_call_fn, call_id, {"status": "failed", "error": "Empty transcript"})
            return

        _safe_update_call(update_call_fn, call_id, {
            "transcript": labelled_transcript,
            "agent_transcript": agent_transcript,
            "status": "scoring",
            **metadata,
        })

        print(f"[PIPELINE] {call_id} scoring {len(labelled_transcript)} chars...", flush=True)
        s = score_transcript(labelled_transcript)
        total = int(s.get("total_score") or 0)
        pct = int(s.get("total_score_pct") or round((total / 20) * 100))

        payload = {
            "status": "processed",
            "score": total,
            "score_pct": pct,
            "grade": s.get("grade", "Poor"),
            "critical_fail": bool(s.get("critical_fail", False)),
            "scores_breakdown": s.get("scores", {}),
            "compliance_flags": s.get("compliance_flags", []),
            "ptp_detected": _bool(s.get("ptp_detected", False)),
            "ptp_amount": s.get("ptp_amount"),
            "ptp_date": s.get("ptp_date"),
            "ptp_mode": s.get("ptp_mode"),
            "disposition": s.get("disposition", "OTHER"),
            "dispositions": [s.get("disposition", "OTHER")],
            "risk_level": s.get("risk_level", "LOW"),
            "ai_detection": s.get("ai_detection", ["NONE"]),
            "ai_suggestion": s.get("ai_suggestion", ""),
            "confidence": int(s.get("confidence") or 80),
            "agent_sentiment": s.get("agent_sentiment", "neutral"),
            "sentiment_notes": s.get("sentiment_notes", ""),
            "summary": s.get("summary", ""),
            "key_issues": s.get("key_issues", []),
            "strengths": s.get("strengths", []),
            "coaching_tip": s.get("coaching_tip", ""),
            "processed_at": datetime.now(timezone.utc).isoformat(),
            **metadata,
        }
        _safe_update_call(update_call_fn, call_id, payload)

        ptp = f"PTP: {s.get('ptp_amount')} on {s.get('ptp_date')}" if s.get("ptp_detected") else "No PTP"
        print(f"[PIPELINE] {call_id} DONE {total}/20 ({s.get('grade')}) | {s.get('disposition')} | {ptp}", flush=True)

    except json.JSONDecodeError as e:
        _safe_update_call(update_call_fn, call_id, {"status": "failed", "error": "Score parse error: " + str(e)})
        print(f"[PIPELINE] {call_id} JSON error: {e}", flush=True)
    except Exception as e:
        _safe_update_call(update_call_fn, call_id, {"status": "failed", "error": str(e)})
        print(f"[PIPELINE] {call_id} ERROR: {e}", flush=True)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def process_call_async(call_id, audio_source, calls_db, update_call_fn):
    t = threading.Thread(target=process_call, args=(call_id, audio_source, calls_db, update_call_fn), daemon=True)
    t.start()
    return t


def export_calls_to_csv_bytes(calls):
    import io, csv
    output = io.StringIO()
    headers = [
        "id", "filename", "agent_id", "loan_id", "status", "score", "score_pct", "grade",
        "critical_fail", "ptp_detected", "ptp_amount", "ptp_date", "ptp_mode",
        "disposition", "risk_level", "ai_detection", "ai_suggestion", "confidence",
        "compliance_flags", "agent_sentiment", "A1_opening", "A2_case_knowledge",
        "A3_probing", "A4_negotiation", "A5_commitment_ptp", "A6_closing",
        "A7_professionalism", "A8_call_handling", "A9_troubleshooting",
        "summary", "key_issues", "strengths", "coaching_tip", "uploaded_at", "processed_at",
    ]
    writer = csv.DictWriter(output, fieldnames=headers, extrasaction="ignore")
    writer.writeheader()
    for c in calls or []:
        bd = c.get("scores_breakdown") or {}
        writer.writerow({
            "id": c.get("id", ""),
            "filename": c.get("filename", ""),
            "agent_id": c.get("agent_id", ""),
            "loan_id": c.get("loan_id", ""),
            "status": c.get("status", ""),
            "score": c.get("score", ""),
            "score_pct": c.get("score_pct", ""),
            "grade": c.get("grade", ""),
            "critical_fail": c.get("critical_fail", ""),
            "ptp_detected": c.get("ptp_detected", ""),
            "ptp_amount": c.get("ptp_amount", ""),
            "ptp_date": c.get("ptp_date", ""),
            "ptp_mode": c.get("ptp_mode", ""),
            "disposition": c.get("disposition", ""),
            "risk_level": c.get("risk_level", ""),
            "ai_detection": "; ".join(_as_list(c.get("ai_detection"))),
            "ai_suggestion": c.get("ai_suggestion", ""),
            "confidence": c.get("confidence", ""),
            "compliance_flags": "; ".join(_as_list(c.get("compliance_flags"))),
            "agent_sentiment": c.get("agent_sentiment", ""),
            "A1_opening": bd.get("A1_opening", ""),
            "A2_case_knowledge": bd.get("A2_case_knowledge", ""),
            "A3_probing": bd.get("A3_probing", ""),
            "A4_negotiation": bd.get("A4_negotiation", ""),
            "A5_commitment_ptp": bd.get("A5_commitment_ptp", ""),
            "A6_closing": bd.get("A6_closing", ""),
            "A7_professionalism": bd.get("A7_professionalism", ""),
            "A8_call_handling": bd.get("A8_call_handling", ""),
            "A9_troubleshooting": bd.get("A9_troubleshooting", ""),
            "summary": c.get("summary", ""),
            "key_issues": "; ".join(_as_list(c.get("key_issues"))),
            "strengths": "; ".join(_as_list(c.get("strengths"))),
            "coaching_tip": c.get("coaching_tip", ""),
            "uploaded_at": c.get("uploaded_at", ""),
            "processed_at": c.get("processed_at", ""),
        })
    return output.getvalue().encode("utf-8")
