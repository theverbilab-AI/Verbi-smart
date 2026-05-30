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
    "critical_fail", "ptp_detected", "processed_at", "agent_id", "loan_id", "analysis",
}
TRAINING_EXAMPLES_PATH = os.getenv(
    "SCORING_TRAINING_FILE",
    os.path.join(os.path.dirname(__file__), "training_data", "scoring_examples.jsonl"),
)


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
    out = dict(payload)
    try:
        from database import clean_fields
        return clean_fields(out, "calls")
    except Exception:
        fallback = {}
        for k, v in out.items():
            if isinstance(v, (list, dict)):
                fallback[k] = json.dumps(v, ensure_ascii=False)
            elif k in {"critical_fail", "ptp_detected"}:
                fallback[k] = _int_bool(v)
            else:
                fallback[k] = v
        return fallback


def _as_list(v):
    if v is None:
        return []
    if isinstance(v, list):
        return [str(x) for x in v if str(x).strip()]
    if isinstance(v, str):
        return [x.strip() for x in re.split(r"[,;|]", v) if x.strip()]
    return [str(v)]


def parse_filename_metadata(filename):
    """Extract agent_id and loan_id from common naming styles."""
    base = os.path.basename(str(filename or ""))
    base = unquote(base.split("?", 1)[0])
    name, _ext = os.path.splitext(base)
    name = name.strip()
    if not name:
        return {"agent_id": "Unknown", "loan_id": "Unknown"}

    cleaned = re.sub(r"^CALL-[A-F0-9]{6,12}_", "", name, flags=re.I)

    # Style: AgentName_LoanNumber
    m = re.match(r"^([A-Za-z][A-Za-z0-9.-]{1,})_(\d{4,}[A-Za-z0-9-]*)$", cleaned, re.I)
    if m:
        return {"agent_id": m.group(1), "loan_id": m.group(2)}

    # Style: AgentLoan-Rita / Agent12345-Rita
    m = re.match(r"^([A-Za-z][A-Za-z]+?)(\d{4,})[-_ ]+([A-Za-z][A-Za-z .'-]*)$", cleaned, re.I)
    if m:
        return {"agent_id": m.group(3).strip(), "loan_id": m.group(2)}

    # Style: Rita-15148 / Rita_15148
    m = re.match(r"^([A-Za-z][A-Za-z .'-]{1,})[-_ ]+(\d{4,}[A-Za-z0-9-]*)$", cleaned, re.I)
    if m:
        return {"agent_id": m.group(1).strip(), "loan_id": m.group(2)}

    if "_" in cleaned:
        parts = [p.strip() for p in cleaned.split("_") if p.strip()]
        if len(parts) >= 2:
            return {"agent_id": parts[0], "loan_id": parts[1]}

    # Last attempt: pick first 4+ digit block as loan id.
    loan_match = re.search(r"\b(\d{4,}[A-Za-z0-9-]*)\b", cleaned)
    if loan_match:
        loan_id = loan_match.group(1)
        left = cleaned[: loan_match.start()].strip(" _-.")
        right = cleaned[loan_match.end() :].strip(" _-.")
        agent_candidate = right or left
        if agent_candidate:
            return {"agent_id": agent_candidate, "loan_id": loan_id}

    return {"agent_id": cleaned, "loan_id": cleaned}


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

    last_err = None
    for attempt in range(1, 4):
        try:
            r = s.get(dl, stream=True, timeout=120, allow_redirects=True)
            r.raise_for_status()

            # Large public files can require a confirmation token.
            token = None
            for k, v in r.cookies.items():
                if "download_warning" in k or "confirm" in k.lower():
                    token = v
                    break
            if token:
                r = s.get(dl + "&confirm=" + token, stream=True, timeout=180, allow_redirects=True)
                r.raise_for_status()

            # Derive extension from headers when available.
            ctype = (r.headers.get("Content-Type") or "").lower()
            ext = ".mp3"
            if "wav" in ctype:
                ext = ".wav"
            elif "mp4" in ctype or "m4a" in ctype:
                ext = ".m4a"
            elif "ogg" in ctype:
                ext = ".ogg"
            elif "flac" in ctype:
                ext = ".flac"
            dest = os.path.join(dest_dir, f"gdrive_{file_id}{ext}")

            expected = int(r.headers.get("Content-Length") or 0)
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
            if expected and total < int(expected * 0.97):
                raise RuntimeError(
                    f"Google Drive partial download ({total}/{expected} bytes) on attempt {attempt}"
                )
            print(f"[GDRIVE] Done {total // 1024}KB (attempt {attempt})", flush=True)
            return dest
        except Exception as exc:
            last_err = exc
            print(f"[GDRIVE] attempt {attempt} failed: {exc}", flush=True)

    raise RuntimeError(f"Google Drive download failed after retries: {last_err}")


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

    uri = s3_uri.replace("s3://", "", 1).strip()
    if "/" not in uri:
        raise ValueError(f"Invalid S3 URI (need s3://bucket/key): {s3_uri}")
    bucket, key = uri.split("/", 1)
    key = key.lstrip("/")
    print(f"[S3] Downloading s3://{bucket}/{key}", flush=True)

    def _candidate_keys(base_key: str) -> list[str]:
        opts = [base_key]
        if base_key.startswith("calls/"):
            opts.append("audio/" + base_key.split("/", 1)[1])
        elif base_key.startswith("audio/"):
            opts.append("calls/" + base_key.split("/", 1)[1])
        return list(dict.fromkeys(opts))

    def _s3_client(region_name: str):
        return boto3.client(
            "s3",
            region_name=region_name,
            aws_access_key_id=os.getenv("AWS_ACCESS_KEY_ID"),
            aws_secret_access_key=os.getenv("AWS_SECRET_ACCESS_KEY"),
        )

    try:
        from storage import resolve_bucket_region
        region = resolve_bucket_region(bucket)
    except Exception:
        region = (
            os.getenv("S3_AUDIO_REGION")
            or os.getenv("AWS_REGION")
            or os.getenv("AWS_DEFAULT_REGION")
            or "eu-north-1"
        )
    client = _s3_client(region)
    try:
        downloaded = False
        for k in _candidate_keys(key):
            dest = os.path.join(dest_dir, os.path.basename(k) or "audio.mp3")
            try:
                client.download_file(bucket, k, dest)
                key = k
                downloaded = True
                if k != uri.split("/", 1)[1].lstrip("/"):
                    print(f"[S3] Download fallback key used: s3://{bucket}/{k}", flush=True)
                break
            except ClientError:
                continue
        if downloaded:
            print(f"[S3] Done {os.path.getsize(dest) // 1024}KB", flush=True)
            return dest
        raise RuntimeError(
            f"S3 object not found on checked prefixes for s3://{bucket}/{key} "
            "(tried both calls/ and audio/ paths)."
        )
    except ClientError as exc:
        code = exc.response.get("Error", {}).get("Code")
        msg = str(exc)

        # Region mismatch is common in S3. Retry once using region hinted by AWS.
        region_hint = None
        hint_match = re.search(r"region[^\w-]*([a-z]{2}-[a-z-]+-\d)", msg, re.I)
        if hint_match:
            region_hint = hint_match.group(1)
        if not region_hint:
            try:
                region_hint = (
                    client.get_bucket_location(Bucket=bucket).get("LocationConstraint")
                    or "us-east-1"
                )
            except Exception:
                region_hint = None
        if region_hint and region_hint != region:
            try:
                retry_client = _s3_client(region_hint)
                retry_client.download_file(bucket, key, dest)
                print(f"[S3] Downloaded using bucket region {region_hint}", flush=True)
                return dest
            except Exception:
                pass

        if code in {"403", "AccessDenied"}:
            raise RuntimeError(
                f"S3 403 Forbidden for s3://{bucket}/{key} (bucket region {region}). "
                "This is almost always IAM: attach s3:GetObject + s3:ListBucket on "
                "arn:aws:s3:::verbilab-care-audio-2026 and arn:aws:s3:::verbilab-care-audio-2026/* "
                "to IAM user verbilab-care, and use those keys in ECS/Railway env. "
                "Deploying the app in ap-south-1 (Mumbai) while the bucket is in eu-north-1 (Stockholm) is fine."
            ) from exc
        if code in {"404", "NoSuchKey", "NoSuchBucket"}:
            raise RuntimeError(
                f"S3 object not found: s3://{bucket}/{key}. "
                "Check bucket name and key path (example: s3://verbilab-care-audio-2026/calls/file.mp3)."
            ) from exc
        raise
    except RuntimeError:
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
    """Resolve ffmpeg: system PATH, Docker apt, or bundled imageio-ffmpeg wheel."""
    custom = os.getenv("FFMPEG_PATH", "").strip()
    if custom and os.path.isfile(custom):
        return custom
    found = shutil.which("ffmpeg")
    if found and os.path.isfile(found):
        return found
    for path in ("/usr/bin/ffmpeg", "/usr/local/bin/ffmpeg"):
        if os.path.isfile(path):
            return path
    try:
        import imageio_ffmpeg
        bundled = imageio_ffmpeg.get_ffmpeg_exe()
        if bundled and os.path.isfile(bundled):
            return bundled
    except Exception as exc:
        print(f"[CHUNK] imageio-ffmpeg unavailable: {exc}", flush=True)
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
    ext = os.path.splitext(chunk_path)[1].lower()
    mime = {
        ".mp3": "audio/mpeg",
        ".wav": "audio/wav",
        ".m4a": "audio/mp4",
        ".aac": "audio/aac",
        ".ogg": "audio/ogg",
        ".flac": "audio/flac",
        ".webm": "audio/webm",
    }.get(ext, "application/octet-stream")
    with open(chunk_path, "rb") as f:
        data = f.read()
    r = requests.post(
        "https://api.sarvam.ai/speech-to-text-translate",
        headers={"api-subscription-key": api_key},
        files={"file": (os.path.basename(chunk_path), data, mime)},
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


def _strip_thinking_blocks(text: str) -> str:
    """Remove chain-of-thought / reasoning blocks from LLM output."""
    if not text:
        return ""
    for pattern in (
        r"<think>[\s\S]*?</think>",
        r"<think>[\s\S]*?</think>",
        r"```[\s\S]*?```",
    ):
        text = re.sub(pattern, "", text, flags=re.I)
    return text.strip()


def _repair_diarization(labelled: str) -> str:
    """Split merged Agent/Customer lines when both speakers appear in one block."""
    if not labelled:
        return labelled

    split_customer = re.compile(
        r"(?<=[.!?,])\s+(?="
        r"no\.?\s*who is speaking|who is speaking|the call got disconnected|"
        r"i am saying|customer:|tell me,?\s*by when|yes,?\s*tell me|"
        r"madam,?\s+we are|madam,?\s+i |sir,?\s+your app|can you send|"
        r"like we deposit|what is not available)",
        re.I,
    )
    split_agent = re.compile(
        r"(?<=[.!?,])\s+(?="
        r"good (?:morning|afternoon|evening)|speaking on behalf|this is|"
        r"sir,?\s*i am|madam,?\s*i am|agent:|hello hello)",
        re.I,
    )

    repaired: list[str] = []
    for raw in labelled.splitlines():
        line = raw.strip()
        if not line:
            continue
        m = re.match(r"^(agent|customer)\s*:\s*(.*)$", line, re.I)
        if not m:
            repaired.append(line)
            continue
        speaker, text = m.group(1).title(), m.group(2).strip()
        if len(text) < 45:
            repaired.append(f"{speaker}: {text}")
            continue

        parts = split_customer.split(text) if speaker == "Agent" else split_agent.split(text)
        if len(parts) <= 1:
            repaired.append(f"{speaker}: {text}")
            continue

        repaired.append(f"{speaker}: {parts[0].strip()}")
        alt = "Customer" if speaker == "Agent" else "Agent"
        for part in parts[1:]:
            part = part.strip()
            if part:
                repaired.append(f"{alt}: {part}")

    return "\n".join(repaired)


def _post_correct_speakers(labelled: str) -> str:
    """Light post-pass to reduce obvious Agent/Customer mis-tags."""
    if not labelled:
        return labelled
    corrected: list[str] = []
    for raw in labelled.splitlines():
        line = raw.strip()
        m = re.match(r"^(agent|customer)\s*:\s*(.*)$", line, re.I)
        if not m:
            continue
        speaker = m.group(1).title()
        text = (m.group(2) or "").strip()
        low = text.lower()

        customer_only = (
            "who is speaking", "wrong number", "don't know", "dont know",
            "not him", "not her", "he is not here", "she is not here",
            "i will be free", "when i am free", "call you later when",
            "in how many minutes will you", "what are you doing",
            "yes, tell me", "yes tell me", "yes, speaking", "yes speaking",
            "hello, hello", "tell me",
        )
        agent_only = (
            "calling from", "speaking on behalf", "this is", "outstanding",
            "emi", "loan amount", "payment", "dpd",
            "won't take much time", "wont take much time", "pick up the phone",
            "better if you talk", "we will take two minutes", "please talk for",
            "speaking with", "am i speaking", "on behalf of", "from apollo", "from tala",
            " ji,", " ji ", "are you speaking",
        )
        if speaker == "Agent" and any(p in low for p in customer_only):
            speaker = "Customer"
        elif speaker == "Customer" and any(p in low for p in agent_only):
            speaker = "Agent"

        corrected.append(f"{speaker}: {text}")
    return "\n".join(corrected)


def format_labelled_transcript(text: str) -> str:
    """Keep only Agent:/Customer: lines — safe for UI and scoring storage."""
    text = _strip_thinking_blocks(text or "")
    if not text:
        return ""
    lines: list[str] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        if re.match(r"^(agent|customer)\s*:", line, re.I):
            m = re.match(r"^(agent|customer)\s*:\s*(.*)$", line, re.I)
            who = m.group(1).title()
            lines.append(f"{who}: {m.group(2).strip()}")
            continue
        for part in re.split(r"(?=(?:agent|customer)\s*:)", line, flags=re.I):
            part = part.strip()
            if part and re.match(r"^(agent|customer)\s*:", part, re.I):
                m = re.match(r"^(agent|customer)\s*:\s*(.*)$", part, re.I)
                who = m.group(1).title()
                lines.append(f"{who}: {m.group(2).strip()}")
    if lines:
        return _post_correct_speakers(_repair_diarization("\n".join(lines)))
    m = re.search(r"(?im)^(agent|customer)\s*:", text)
    if m:
        return format_labelled_transcript(text[m.start():])
    return ""


def _heuristic_bifurcate(text):
    """Fallback when LLM diarisation fails. Keeps transcript readable and avoids blank agent text."""
    text = re.sub(r"\s+", " ", text or "").strip()
    if not text:
        return "", ""
    sentences = re.split(r"(?<=[.!?])\s+", text)
    turns = []
    speaker = "Agent"
    customer_cues = re.compile(
        r"\b(i don'?t|i have|my job|can you|hello\??|i will|unable|problem|issue|lost my|money|"
        r"who is speaking|call got disconnected|i am saying|mera naam|tell me|yes tell me|"
        r"yes speaking|yes, speaking|boliye|bolo)\b",
        re.I,
    )
    agent_cues = re.compile(
        r"\b(company|bank|loan|emi|payment|outstanding|overdue|calling|speaking on behalf|"
        r"good morning|good afternoon|this is|ok credit|tala|amount|due|sir|madam)\b",
        re.I,
    )
    for sent in sentences:
        sent = sent.strip()
        if not sent:
            continue
        low = sent.lower()
        if customer_cues.search(sent) and not agent_cues.search(sent[:80]):
            speaker = "Customer"
        elif agent_cues.search(sent):
            speaker = "Agent"
        elif low.endswith("?") and any(x in low for x in ("who", "what", "where", "why", "how")):
            # Natural customer clarifying questions in fallback transcripts.
            speaker = "Customer"
        turns.append(f"{speaker}: {sent}")
        # Do not force alternate speaker; switch only when cues indicate a change.
    labelled = "\n".join(turns)
    agent = "\n".join(line for line in turns if line.startswith("Agent:")) or text
    return agent, labelled


def bifurcate_transcript(raw_text: str, api_key: str) -> tuple[str, str]:
    """Agent/Customer bifurcation — LLM first, heuristic fallback."""
    raw_text = re.sub(r"\s+", " ", (raw_text or "")).strip()
    if not raw_text:
        return "", ""
    try:
        agent, labelled = _diarize_with_llm(raw_text, api_key)
        labelled = format_labelled_transcript(labelled) or labelled
        if labelled:
            return agent, labelled
    except Exception as exc:
        print(f"[BIFURCATION] LLM failed, using heuristic: {exc}", flush=True)
    return _heuristic_bifurcate(raw_text)


def _diarize_with_llm(raw_transcript, api_key):
    """Use the chat model to convert raw ASR text into Agent/Customer turns."""
    if not raw_transcript.strip():
        return "", ""
    prompt = f"""
Convert this collections call transcript into speaker turns.

RULES (strict):
- Output ONLY dialogue lines. Each line MUST start with exactly "Agent:" or "Customer:".
- ONE speaker per line only. Never put Agent and Customer dialogue in the same line.
- Agent = company/collector. Customer = borrower. Alternate turns when speakers change.
- Do NOT include reasoning, planning, notes, or XML tags.
- Do NOT summarize or skip lines. Include the FULL call: opening disclaimer, agent intro, RPC, loan details, negotiation, closing.
- Preserve exact payment amounts, dates, loan details, objections, Hindi/English mix, and compliance disclosures.
- If unsure who spoke, infer from context (questions about payment = often Agent).

RAW TRANSCRIPT:
{raw_transcript[:9000]}
""".strip()
    r = requests.post(
        "https://api.sarvam.ai/v1/chat/completions",
        headers={"Authorization": "Bearer " + api_key, "Content-Type": "application/json"},
        json={
            "model": os.getenv("SARVAM_CHAT_MODEL", "sarvam-m"),
            "messages": [
                {"role": "system", "content": "You label call transcripts. Output ONLY Agent: and Customer: lines. Never output thinking or notes."},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.0,
            "max_tokens": 2048,
        },
        timeout=90,
    )
    if r.status_code != 200:
        raise RuntimeError(f"Diarization LLM {r.status_code}: {r.text[:200]}")
    labelled = format_labelled_transcript(r.json()["choices"][0]["message"]["content"])
    if not labelled or not re.search(r"(?im)^agent\s*:", labelled):
        raise ValueError("LLM did not return speaker labels")
    agent = "\n".join(line.strip() for line in labelled.splitlines() if line.strip().lower().startswith("agent:"))
    return agent or labelled, labelled


def transcribe(audio_path):
    key = os.getenv("SARVAM_API_KEY")
    if not key:
        raise EnvironmentError("SARVAM_API_KEY not set")

    mb = os.path.getsize(audio_path) / 1024 / 1024
    print(f"[STT] {os.path.basename(audio_path)} ({round(mb, 1)} MB)", flush=True)
    try:
        chunks, tmpdir = split_audio(audio_path)
    except FileNotFoundError as exc:
        print(f"[STT] ffmpeg error ({exc}) — full-file transcription", flush=True)
        chunks, tmpdir = [audio_path], None
    try:
        if len(chunks) == 1:
            _, raw_text = _transcribe_chunk(chunks[0], key, 0)
        else:
            results = {}
            with ThreadPoolExecutor(max_workers=min(3, len(chunks))) as ex:
                futs = {ex.submit(_transcribe_chunk, c, i and key or key, i): i for i, c in enumerate(chunks)}
                for f in as_completed(futs):
                    i, t = f.result()
                    results[i] = t
            raw_text = " ".join(results[i] for i in sorted(results))
        raw_text = re.sub(r"\s+", " ", raw_text or "").strip()
        print(f"[STT] Raw done {len(raw_text)} chars", flush=True)
        if len(raw_text) < 4:
            raise RuntimeError(
                "No speech detected from audio. Check recording quality/codec (try wav/mp3) or verify file is valid audio."
            )

        from scoring_rules import cleanup_transcript_for_scoring

        agent_transcript, labelled = bifurcate_transcript(raw_text, key)
        labelled = cleanup_transcript_for_scoring(labelled)
        agent_transcript = agent_transcript or "\n".join(
            ln for ln in labelled.splitlines() if ln.strip().lower().startswith("agent:")
        )
        print(
            f"[BIFURCATION] labelled {len(labelled)} chars | agent {len(agent_transcript)} chars",
            flush=True,
        )
        return agent_transcript, labelled
    finally:
        if tmpdir:
            shutil.rmtree(tmpdir, ignore_errors=True)


SCORING_PROMPT = """You are a strict but fair QA auditor for an Indian collections call centre.
Score ONLY the AGENT using the labelled transcript. Output ONLY raw JSON starting with {{. No thinking.

IMPORTANT COMPLIANCE RULES:
1. Right Party Contact / RPC must happen before disclosing loan amount, overdue, EMI, legal/payment details.
2. NEVER add compliance flag RPC_MISSED if the customer confirmed identity (yes speaking, this is [name], haan ji, etc.).
3. WRONG_NUMBER or non-collections calls (no loan/EMI/payment discussion): disposition WRONG_NUMBER or OTHER, flag NOT_COLLECTIONS, total_score must be 0-4 only (not 100%).
4. If a third party answers, agent must NOT disclose loan details. WRONG_DISCLOSURE if disclosed to third party.
5. PTP RULES (STRICT):
   - A valid PTP needs (a) an amount or "full payment / part payment", (b) a date or near-term reference (today/tomorrow/by DD/MM/by Friday/within X days), and (c) a payment mode (UPI/NEFT/cash/online/link).
   - If ALL THREE present → ptp_detected=true, disposition=PTP, fill ptp_amount/ptp_date/ptp_mode exactly as customer said.
   - If 1-2 of the 3 → vague commitment: ptp_detected=false, disposition=CALLBACK, A5_commitment_ptp=1.
   - If customer refuses or no commitment → ptp_detected=false, disposition=OTHER/NO_PTP, A5_commitment_ptp=0.
   - NEVER mark ptp_detected=true on WRONG_NUMBER or non-collections calls.

A1 OPENING (0-2) — score strictly:
- 2 = call recording disclaimer + agent/company intro + customer name used + RPC confirmed before loan details
- 1 = most elements present, one missing (e.g. no disclaimer but RPC confirmed)
- 0 = no RPC on a collections call, or no intro/disclaimer on collections call

A2 CASE KNOWLEDGE (0-2): amount + DPD + loan context after RPC
A3 PROBING (0-3) CRITICAL: deep reason + follow-up questions, not vague acceptance
A4 NEGOTIATION (0-3) CRITICAL: urgency + options + consequences/benefits
A5 COMMITMENT (0-3) CRITICAL: PTP needs amount + date + mode; vague promise = 1 max
A6 CLOSING (0-2): reconfirm PTP/payment + professional sign-off
A7 PROFESSIONALISM (0-3) CRITICAL: 0 if threat/abuse; empathy + courtesy otherwise
A8 CALL HANDLING (0-1): outcome-focused, no drift
A9 TROUBLESHOOTING (0-1): resolves app/link/UPI issues

Non-collections or wrong-number: total_score max 4, flag NOT_COLLECTIONS.
RPC_MISSED only if loan disclosed without confirmed RPC.

FRAMEWORK (20 pts total) — score each parameter independently:
A1 Opening (0-2) | A2 Case Knowledge (0-2) | A3 Probing (0-3) | A4 Negotiation (0-3)
A5 Commitment/PTP (0-3) | A6 Closing (0-2) | A7 Professionalism (0-3)
A8 Call Handling (0-1) | A9 Troubleshooting (0-1)

Allowed dispositions:
PTP, CALLBACK, DISCONNECTED, PAYMENT_ISSUE, LANGUAGE_ISSUE, APP_NOT_WORKING, FINANCIAL_HARDSHIP, MEDICAL_ISSUE, DISPUTE, THIRD_PARTY, WRONG_NUMBER, NO_RESPONSE, OTHER

Allowed compliance flags:
THREAT, ABUSE, FALSE_PROMISE, WRONG_DISCLOSURE, RPC_MISSED, PTP_DETECTED, NO_PTP, THIRD_PARTY_SAFE, THIRD_PARTY_BREACH, NOT_COLLECTIONS, NONE

{few_shot_block}

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


def _tokenize_for_similarity(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z]{3,}", (text or "").lower()) if w not in {"agent", "customer", "call"}}


def _load_scoring_training_examples() -> list[dict]:
    path = TRAINING_EXAMPLES_PATH
    if not os.path.isfile(path):
        return []
    examples = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except Exception:
                continue
            if row.get("transcript") and row.get("expected_json"):
                examples.append(row)
    return examples


def append_scoring_training_example(example: dict) -> None:
    """Persist one reviewed call as a training example for few-shot scoring."""
    os.makedirs(os.path.dirname(TRAINING_EXAMPLES_PATH), exist_ok=True)
    row = {
        "id": example.get("id"),
        "tags": example.get("tags") or [],
        "transcript": str(example.get("transcript") or "")[:6000],
        "expected_json": example.get("expected_json") or {},
    }
    with open(TRAINING_EXAMPLES_PATH, "a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")


def call_to_training_example(call: dict, *, tags: list[str] | None = None, override: dict | None = None) -> dict:
    """Build a few-shot row from a processed call record (DB shape)."""
    transcript = str(call.get("transcript") or "").strip()
    expected = override or {
        "scores": call.get("scores_breakdown") or {},
        "total_score": call.get("score") or 0,
        "total_score_pct": call.get("score_pct") or 0,
        "grade": call.get("grade") or "Poor",
        "critical_fail": bool(call.get("critical_fail")),
        "ptp_detected": bool(call.get("ptp_detected")),
        "ptp_amount": call.get("ptp_amount"),
        "ptp_date": call.get("ptp_date"),
        "ptp_mode": call.get("ptp_mode"),
        "disposition": call.get("disposition") or "OTHER",
        "risk_level": call.get("risk_level") or "LOW",
        "ai_detection": call.get("ai_detection") or ["NONE"],
        "ai_suggestion": call.get("ai_suggestion") or "",
        "agent_sentiment": call.get("agent_sentiment") or "neutral",
        "sentiment_notes": call.get("sentiment_notes") or "",
        "compliance_flags": call.get("compliance_flags") or ["NONE"],
        "confidence": int(call.get("confidence") or 80),
        "summary": call.get("summary") or "",
        "key_issues": call.get("key_issues") or [],
        "strengths": call.get("strengths") or [],
        "coaching_tip": call.get("coaching_tip") or "",
    }
    auto_tags = list(tags or [])
    disp = str(call.get("disposition") or "").lower()
    if call.get("ptp_detected") and "ptp" not in auto_tags:
        auto_tags.append("ptp")
    if disp:
        auto_tags.append(disp.replace(" ", "_"))
    analysis = call.get("analysis") or {}
    for issue in (analysis.get("customer_issues") or [])[:3]:
        auto_tags.append(str(issue).lower())
    opening = (analysis.get("opening_audit") or {})
    if opening.get("rpc_confirmed") and "rpc" not in auto_tags:
        auto_tags.append("rpc")
    if opening.get("agent_intro_done") and "opening" not in auto_tags:
        auto_tags.append("opening")
    return {
        "id": call.get("id") or call.get("call_id"),
        "tags": sorted(set(auto_tags)),
        "transcript": transcript,
        "expected_json": expected,
    }


def _infer_query_tags(transcript: str) -> set[str]:
    try:
        from scoring_rules import detect_call_kpis
        kpis = detect_call_kpis(transcript)
    except Exception:
        return set()
    tags: set[str] = set()
    if kpis.get("rpc_confirmed"):
        tags.add("rpc")
    if kpis.get("ptp_detected"):
        tags.add("ptp")
    if kpis.get("third_party"):
        tags.add("third_party")
    if kpis.get("compliance_violation"):
        tags.add("third_party_breach")
    for issue in kpis.get("customer_issues") or []:
        tags.add(str(issue).lower())
    for disp in kpis.get("dispositions") or []:
        tags.add(str(disp).lower())
    return tags


def seed_scoring_examples_from_calls(
    calls: list[dict],
    *,
    min_score_pct: int = 70,
    max_examples: int = 12,
    merge: bool = True,
) -> dict:
    """
    Pick diverse high-scoring processed calls and write scoring_examples.jsonl.
    Returns summary counts.
    """
    eligible = [
        c for c in calls
        if str(c.get("status") or "").lower() == "processed"
        and str(c.get("transcript") or "").strip()
        and int(c.get("score_pct") or c.get("score") or 0) >= min_score_pct
    ]
    eligible.sort(
        key=lambda c: (
            int(c.get("score_pct") or c.get("score") or 0),
            str(c.get("uploaded_at") or ""),
        ),
        reverse=True,
    )

    seen_tags: set[str] = set()
    picked: list[dict] = []
    for call in eligible:
        if len(picked) >= max_examples:
            break
        ex = call_to_training_example(call)
        tag_key = ",".join(sorted(ex.get("tags") or [])[:4]) or "generic"
        if tag_key in seen_tags and len(picked) >= max_examples // 2:
            continue
        seen_tags.add(tag_key)
        picked.append(ex)

    os.makedirs(os.path.dirname(TRAINING_EXAMPLES_PATH), exist_ok=True)
    existing: list[dict] = _load_scoring_training_examples() if merge else []
    existing_ids = {str(x.get("id")) for x in existing if x.get("id")}
    added = 0
    with open(TRAINING_EXAMPLES_PATH, "a" if merge else "w", encoding="utf-8") as f:
        if not merge:
            for row in picked:
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
                added += 1
        else:
            for row in picked:
                if str(row.get("id")) in existing_ids:
                    continue
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
                added += 1

    return {
        "eligible_calls": len(eligible),
        "picked": len(picked),
        "added": added,
        "total_in_file": len(_load_scoring_training_examples()),
        "path": TRAINING_EXAMPLES_PATH,
    }


def _build_few_shot_block(transcript: str, max_examples: int = 2) -> str:
    examples = _load_scoring_training_examples()
    if not examples:
        return ""
    q = _tokenize_for_similarity(transcript)
    query_tags = _infer_query_tags(transcript)
    ranked = []
    for ex in examples:
        t = _tokenize_for_similarity(ex.get("transcript", ""))
        ex_tags = {str(x).lower() for x in (ex.get("tags") or [])}
        tag_score = len(query_tags & ex_tags) * 4
        token_score = len(q & t)
        ranked.append((tag_score + token_score, ex))
    ranked.sort(key=lambda x: x[0], reverse=True)
    selected = [ex for score, ex in ranked[:max_examples] if score > 0] or [ex for _, ex in ranked[:1]]

    parts = ["REFERENCE TRAINING EXAMPLES (match style, do not copy blindly):"]
    for i, ex in enumerate(selected, 1):
        parts.append(f"Example {i} Transcript:")
        parts.append(str(ex.get("transcript", "")).strip()[:1500])
        parts.append(f"Example {i} Expected JSON:")
        parts.append(json.dumps(ex.get("expected_json") or {}, ensure_ascii=False)[:2200])
    return "\n".join(parts)


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


def _calibrate_scores_from_transcript(
    result: dict, transcript: str, filename_hint: str = ""
) -> dict:
    """Rule-based partial credit so greeting/intro are not scored 0 when clearly present."""
    scores = dict(result.get("scores") or {})
    agent_text = " ".join(
        line.split(":", 1)[1].strip()
        for line in transcript.splitlines()
        if re.match(r"^\s*agent\s*:", line, re.I) and ":" in line
    ).lower()
    if not agent_text:
        agent_text = transcript.lower()

    def bump(key: str, minimum: int, maximum: int):
        scores[key] = max(scores.get(key, 0), minimum)
        scores[key] = min(scores[key], maximum)

    has_greeting = any(p in agent_text for p in (
        "good morning", "good afternoon", "good evening", "hello", "namaste", "hi sir", "hi madam",
    ))
    has_intro = any(p in agent_text for p in (
        "speaking on behalf", "calling from", "this is", "my name", "from tala", "from the",
        "on behalf of", "i am", "i'm",
    ))
    has_rpc = any(p in agent_text for p in (
        "am i speaking", "is this", "confirm", "your name", "right party", "are you mr", "are you ms",
    ))

    if has_greeting or has_intro:
        bump("A1_opening", 1, 2)
    if has_greeting and has_intro:
        bump("A1_opening", 2, 2)
    if has_rpc and (has_greeting or has_intro):
        bump("A1_opening", 2, 2)

    result["scores"] = scores
    try:
        from scoring_rules import cleanup_transcript_for_scoring, run_hybrid_scoring

        transcript = cleanup_transcript_for_scoring(transcript)
        result = run_hybrid_scoring(result, transcript, filename_hint)
    except Exception as exc:
        print(f"[SCORE] Phase1 rules skipped: {exc}", flush=True)
        total = sum(scores.values())
        result["total_score"] = total
        result["total_score_pct"] = int(round((total / 20) * 100))
        result["grade"] = "Excellent" if total >= 18 else "Good" if total >= 14 else "Needs Improvement" if total >= 8 else "Poor"
        critical = ["A3_probing", "A4_negotiation", "A5_commitment_ptp", "A7_professionalism"]
        result["critical_fail"] = bool(any(scores.get(k, 0) == 0 for k in critical))
    return result


def _fallback_score(transcript):
    lower = transcript.lower()
    flags = []
    disposition = "OTHER"
    detections = []

    if any(x in lower for x in ["lost my job", "no job", "financial problem", "no money", "unable to pay", "hardship"]):
        disposition = "FINANCIAL_HARDSHIP"
        detections.append("Financial Hardship Detected")
    if any(x in lower for x in ["hospital", "medical", "surgery", "health issue", "admitted", "doctor"]):
        disposition = "MEDICAL_ISSUE"
        detections.append("Medical Issue Detected")
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

    agent_only = " ".join(
        line.split(":", 1)[1] for line in transcript.splitlines()
        if line.strip().lower().startswith("agent:") and ":" in line
    ).lower() or lower
    has_opening = any(x in agent_only for x in [
        "good morning", "good afternoon", "hello", "speaking on behalf", "calling from", "on behalf",
    ])
    scores = {
        "A1_opening": 2 if has_opening else 1 if any(x in agent_only for x in ["hello", "sir", "madam"]) else 0,
        "A2_case_knowledge": 1 if any(x in lower for x in ["amount", "outstanding", "emi", "overdue", "pending"]) else 0,
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
        "critical_fail": bool(any(scores[k] == 0 for k in ["A3_probing", "A4_negotiation", "A5_commitment_ptp", "A7_professionalism"])),
        "ptp_detected": bool("PTP_DETECTED" in flags),
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


def score_transcript(labelled_transcript, filename_hint: str = ""):
    key = os.getenv("SARVAM_API_KEY")
    if not key:
        raise EnvironmentError("SARVAM_API_KEY not set")
    from scoring_rules import cleanup_transcript_for_scoring

    labelled_transcript = cleanup_transcript_for_scoring(
        format_labelled_transcript(labelled_transcript) or labelled_transcript
    )
    if not labelled_transcript.strip():
        raise ValueError("Empty transcript after cleanup")
    prompt = SCORING_PROMPT.format(
        transcript=labelled_transcript[:10000],
        few_shot_block=_build_few_shot_block(labelled_transcript),
    )

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
    result = _calibrate_scores_from_transcript(result, labelled_transcript, filename_hint)
    fixed_scores = result["scores"]

    total = sum(fixed_scores.values())
    if "_scoring_calibration" not in result:
        result["total_score"] = total
        result["total_score_pct"] = int(round((total / 20) * 100))
        result["grade"] = "Excellent" if total >= 18 else "Good" if total >= 14 else "Needs Improvement" if total >= 8 else "Poor"
        critical = ["A3_probing", "A4_negotiation", "A5_commitment_ptp", "A7_professionalism"]
        result["critical_fail"] = bool(any(fixed_scores.get(k, 0) == 0 for k in critical))
    else:
        total = int(result.get("total_score") or total)
    result["ptp_detected"] = bool(_bool(result.get("ptp_detected")))
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
            _safe_update_call(
                update_call_fn,
                call_id,
                {
                    "status": "failed",
                    "error": "No labelled transcript generated. Recording may be silent/too short or unsupported.",
                },
            )
            return

        display_transcript = format_labelled_transcript(labelled_transcript) or labelled_transcript
        _safe_update_call(update_call_fn, call_id, {
            "transcript": display_transcript,
            "agent_transcript": agent_transcript,
            "status": "scoring",
            **metadata,
        })

        print(f"[PIPELINE] {call_id} scoring {len(labelled_transcript)} chars...", flush=True)
        source_name = os.path.basename(str(local))
        s = score_transcript(labelled_transcript, source_name)
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
            "ptp_detected": bool(s.get("ptp_detected", False)),
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
            "analysis": {
                "opening_audit": s.get("opening_audit") or {},
                "scoring_calibration": s.get("_scoring_calibration") or {},
                "customer_issues": s.get("customer_issues") or [],
            },
            **metadata,
        }
        _safe_update_call(update_call_fn, call_id, payload)

        if os.path.isfile(str(local)):
            playback_name = os.path.basename(str(local))
            upload_dir = os.path.join(os.path.dirname(__file__), "uploads")
            try:
                from storage import archive_local_audio, persist_playback_copy
                s3_uri = archive_local_audio(str(local), call_id, playback_name)
                if s3_uri:
                    _safe_update_call(update_call_fn, call_id, {"file_path": s3_uri})
                else:
                    cached = persist_playback_copy(str(local), call_id, playback_name, upload_dir)
                    if cached:
                        _safe_update_call(update_call_fn, call_id, {"file_path": cached})
            except Exception as exc:
                print(f"[PIPELINE] S3 archive skipped: {exc}", flush=True)

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


def reprocess_call_from_existing(call_id, call_row, update_call_fn):
    """
    Re-score and re-tag an already processed call using stored transcript + filename.
    Avoids re-downloading audio and is safe for bulk backfill jobs.
    """
    try:
        transcript = str((call_row or {}).get("transcript") or "").strip()
        if not transcript:
            raise RuntimeError("Transcript missing; cannot reprocess without stored dialogue.")

        labelled = format_labelled_transcript(transcript) or transcript
        source_name = (
            (call_row or {}).get("filename")
            or (call_row or {}).get("file_path")
            or (call_row or {}).get("source_uri")
            or ""
        )
        metadata = parse_filename_metadata(source_name)
        s = score_transcript(labelled, source_name)
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
            "ptp_detected": bool(s.get("ptp_detected", False)),
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
            "transcript": labelled,
            "processed_at": datetime.now(timezone.utc).isoformat(),
            "analysis": {
                "opening_audit": s.get("opening_audit") or {},
                "scoring_calibration": s.get("_scoring_calibration") or {},
                "reprocessed": True,
            },
            **metadata,
        }
        _safe_update_call(update_call_fn, call_id, payload)
        print(f"[REPROCESS] {call_id} done {total}/20 ({s.get('grade')})", flush=True)
        return True
    except Exception as exc:
        _safe_update_call(
            update_call_fn,
            call_id,
            {"status": "failed", "error": f"Reprocess failed: {exc}", "processed_at": datetime.now(timezone.utc).isoformat()},
        )
        print(f"[REPROCESS] {call_id} failed: {exc}", flush=True)
        return False


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
