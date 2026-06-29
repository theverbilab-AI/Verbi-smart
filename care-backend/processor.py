"""
CARE Processing Pipeline v10 - PRD aligned, PostgreSQL safe
- Speaker-labelled transcript cleanup: Agent / Customer turns
- Agent + loan metadata extraction from filename pattern: Agent_123456.wav
- PRD scoring prompt with third-party/RPC disclosure handling
- Disposition, AI detection, AI suggestion, risk level, confidence fields
- Safer PostgreSQL updates: retries when optional columns are not present yet
- S3/Drive/direct URL ingestion retained
"""

from __future__ import annotations

import os, json, re, threading, tempfile, shutil, subprocess
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone, timedelta
from urllib.parse import urlparse, unquote
import requests

from agent_parse import parse_filename_metadata
from speaker_attribution import attribute_transcript, to_labelled_text

CHUNK_SECONDS = int(os.getenv("CARE_CHUNK_SECONDS", "25"))
# Sarvam saaras STT rejects audio >30s per request (use batch API above that).
SARVAM_STT_MAX_SECONDS = int(os.getenv("SARVAM_STT_MAX_SECONDS", "28"))
_PROCESS_SEM = threading.Semaphore(max(1, int(os.getenv("CARE_MAX_PARALLEL_PROCESSING", "2"))))
_MAX_PIPELINE_RETRIES = max(1, int(os.getenv("CARE_MAX_PIPELINE_RETRIES", "3")))
CHUNK_OVERLAP_SECONDS = int(os.getenv("CARE_CHUNK_OVERLAP_SECONDS", "3"))
DIARIZATION_MIN_COVERAGE = float(os.getenv("CARE_DIARIZATION_MIN_COVERAGE", "0.62"))
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
        from botocore.exceptions import ClientError, NoCredentialsError
        from storage import resolve_bucket_region, _candidate_s3_keys, _s3_client, s3_configured
    except ImportError:
        raise ImportError("Run: pip install boto3")

    if not s3_configured():
        raise RuntimeError(
            "S3 credentials missing on this server. Add AWS_ACCESS_KEY_ID and "
            "AWS_SECRET_ACCESS_KEY to care-backend/.env (bucket: verbilab-care-audio-2026, "
            "region: eu-north-1). For local dev you can re-upload the file instead of S3 ingest."
        )

    uri = s3_uri.replace("s3://", "", 1).strip()
    if "/" not in uri:
        raise ValueError(f"Invalid S3 URI (need s3://bucket/key): {s3_uri}")
    bucket, key = uri.split("/", 1)
    key = key.lstrip("/")
    region = resolve_bucket_region(bucket)
    print(f"[S3] Downloading s3://{bucket}/{key} (region {region})", flush=True)

    client = _s3_client(bucket)
    last_err = None
    for k in _candidate_s3_keys(key):
        dest = os.path.join(dest_dir, os.path.basename(k) or "audio.mp3")
        try:
            client.download_file(bucket, k, dest)
            if k != key:
                print(f"[S3] Download fallback key used: s3://{bucket}/{k}", flush=True)
            print(f"[S3] Done {os.path.getsize(dest) // 1024}KB", flush=True)
            return dest
        except ClientError as exc:
            last_err = exc
            continue

    code = ""
    if last_err is not None:
        code = getattr(last_err, "response", {}).get("Error", {}).get("Code", "")
    if code in {"403", "AccessDenied"}:
        raise RuntimeError(
            f"S3 403 Forbidden for s3://{bucket}/{key} (bucket region {region}). "
            "Set S3_AUDIO_REGION=eu-north-1 in server .env. "
            "IAM user verbilab-care needs s3:GetObject + s3:PutObject + s3:ListBucket on "
            "arn:aws:s3:::verbilab-care-audio-2026 and arn:aws:s3:::verbilab-care-audio-2026/*"
        ) from last_err
    raise RuntimeError(
        f"S3 object not found for s3://{bucket}/{key} (tried calls/ and audio/ prefixes)."
    ) from last_err


def _find_upload_cache(call_id: str) -> str | None:
    upload_dir = os.path.join(os.path.dirname(__file__), "uploads")
    if not os.path.isdir(upload_dir):
        return None
    prefix = f"{call_id}_"
    for name in os.listdir(upload_dir):
        if name.startswith(prefix):
            path = os.path.join(upload_dir, name)
            if os.path.isfile(path):
                return path
    return None


def _resolve_processing_audio(call_id: str, audio_source, call_row: dict, dest_dir: str) -> str:
    """
    Prefer local/cached files for processing; only hit S3 when configured.
  """
    source = str(audio_source or "").strip()
    row = call_row or {}

    if source and os.path.isfile(source):
        return source

    for key in ("source_uri", "file_path"):
        candidate = str(row.get(key) or "").strip()
        if candidate and os.path.isfile(candidate):
            return candidate

    cached = _find_upload_cache(call_id)
    if cached:
        return cached

    remote = source or str(row.get("file_path") or "").strip()
    if remote.startswith("s3://"):
        return fetch_from_s3(remote, dest_dir)
    if remote:
        return resolve_audio_source(remote, dest_dir)
    raise RuntimeError("No audio file found for this call — re-upload the recording.")


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


def _probe_audio_duration_sec(path: str) -> float | None:
    ffmpeg = _ffmpeg_bin()
    if not ffmpeg:
        return None
    try:
        r = subprocess.run(
            [ffmpeg, "-hide_banner", "-i", path],
            capture_output=True,
            text=True,
        )
        m = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", r.stderr or "")
        if not m:
            return None
        h, mnt, sec = int(m.group(1)), int(m.group(2)), float(m.group(3))
        return h * 3600 + mnt * 60 + sec
    except Exception:
        return None


def _split_oversized_chunks(chunks: list[str], max_sec: float) -> list[str]:
    """Re-split any chunk longer than Sarvam's per-request limit."""
    out: list[str] = []
    for path in chunks:
        dur = _probe_audio_duration_sec(path)
        if dur is None or dur <= max_sec:
            out.append(path)
            continue
        print(f"[CHUNK] Re-splitting {os.path.basename(path)} ({dur:.1f}s > {max_sec}s)", flush=True)
        sub_chunks, _ = split_audio(path, chunk_sec=max(10, int(max_sec) - 2))
        out.extend(sub_chunks if sub_chunks else [path])
    return out


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
    chunks = _split_oversized_chunks(chunks, SARVAM_STT_MAX_SECONDS)
    print(f"[CHUNK] {len(chunks)} chunks of ~{chunk_sec}s (max {SARVAM_STT_MAX_SECONDS}s for STT)", flush=True)
    return chunks, tmpdir


def _transcribe_chunk(chunk_path, api_key, idx, retries=3):
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
    last_err = ""
    for attempt in range(1, retries + 1):
        try:
            r = requests.post(
                "https://api.sarvam.ai/speech-to-text-translate",
                headers={"api-subscription-key": api_key},
                files={"file": (os.path.basename(chunk_path), data, mime)},
                data={
                    "model": "saaras:v3",
                    "language_code": "unknown",
                    "target_language_code": "en-IN",
                },
                timeout=90,
            )
            if r.status_code != 200:
                last_err = f"HTTP {r.status_code}: {r.text[:200]}"
                print(f"[CHUNK {idx}] attempt {attempt} error {last_err}", flush=True)
                continue
            text = r.json().get("transcript", "").strip()
            if len(text) < 2 and attempt < retries:
                print(f"[CHUNK {idx}] attempt {attempt} empty — retrying", flush=True)
                continue
            print(f"[CHUNK {idx}] {len(text)} chars (attempt {attempt})", flush=True)
            return idx, text
        except Exception as exc:
            last_err = str(exc)
            print(f"[CHUNK {idx}] attempt {attempt} failed: {exc}", flush=True)
    print(f"[CHUNK {idx}] FAILED after {retries} attempts: {last_err}", flush=True)
    return idx, ""


def _merge_chunk_transcripts(results: dict[int, str]) -> str:
    """Join chunk STT in order; warn on gaps so missing openings are visible in logs."""
    parts: list[str] = []
    for i in sorted(results):
        text = (results.get(i) or "").strip()
        if not text:
            print(f"[STT] WARNING: chunk {i} produced no text — opening/middle audio may be missing", flush=True)
            continue
        parts.append(text)
    return re.sub(r"\s+", " ", " ".join(parts)).strip()


def _word_coverage(raw: str, labelled: str) -> float:
    """How much of raw STT vocabulary appears in labelled dialogue (0–1)."""
    raw_words = {w for w in re.findall(r"[a-z0-9]{3,}", (raw or "").lower())}
    labelled_words = {w for w in re.findall(r"[a-z0-9]{3,}", (labelled or "").lower())}
    if not raw_words:
        return 1.0
    return len(raw_words & labelled_words) / len(raw_words)


def _is_meta_or_noise_line(text: str) -> bool:
    """Drop LLM reasoning / prompt echo — not real call dialogue."""
    t = (text or "").strip()
    if not t or t in {".", "..", "...", "*", "-", "—"}:
        return True
    if len(t) < 3:
        return True
    low = t.lower()
    meta_cues = (
        "rules are strict", "need to be careful", "customer is the borrower",
        "numbers and dates", "must stay as they are", "should be preserved",
        "mix of hindi and english", "output only", "each line must",
        "never put agent and customer", "infer from context", "do not summarize",
        "preserve exact payment", "labelled transcript", "speaker turns",
        "i need to convert", "let me analyze", "here is the", "here's the",
        "transcript:", "note:", "important:", "strictly", "as an ai",
        "redacted_thinking", "chain of thought", "raw transcript:",
        "convert this collections", "fallback scoring", "model json was unavailable",
        "ai json unavailable", "rule-based engine", "reprocess after deploy",
        "scored using deterministic", "needs manual qa review",
    )
    if any(c in low for c in meta_cues):
        return True
    leak_words = ("instruction", "prompt", "schema")
    if any(w in low for w in leak_words):
        return True
    if re.search(r"\bjson\b", low) and not re.match(r"^(agent|customer)\s*:", t, re.I):
        return True
    if low.startswith("system:") or low.startswith("system "):
        return True
    if re.match(r"^[\W\d\s]+$", t):
        return True
    if low.startswith("*") and "lines" in low:
        return True
    return False


def _filter_labelled_lines(labelled: str) -> str:
    """Keep only real Agent/Customer dialogue lines."""
    kept: list[str] = []
    for raw in (labelled or "").splitlines():
        m = re.match(r"^(agent|customer)\s*:\s*(.*)$", raw.strip(), re.I)
        if not m:
            continue
        who = m.group(1).title()
        body = (m.group(2) or "").strip()
        if _is_meta_or_noise_line(body):
            continue
        kept.append(f"{who}: {body}")
    return "\n".join(kept)


def _transcript_has_dialogue(labelled: str, min_lines: int = 2) -> bool:
    lines = [ln for ln in (labelled or "").splitlines() if re.match(r"^(agent|customer)\s*:", ln.strip(), re.I)]
    return len(lines) >= min_lines


def _strip_thinking_blocks(text: str) -> str:
    """Remove chain-of-thought / reasoning blocks from LLM output."""
    if not text:
        return ""
    for pattern in (
        r"<think>[\s\S]*?</think>",
        r"```[\s\S]*?```",
    ):
        text = re.sub(pattern, "", text, flags=re.I)
    return text.strip()


_STRONG_AGENT_PHRASES = (
    "speaking on behalf", "on behalf of", "calling from", "call is being recorded",
    "this call is recorded", "call is recorded", "recorded for quality",
    "am i speaking with", "may i speak with", "your emi", "your loan",
    "outstanding", "overdue", "you have to pay", "please pay", "payment is due",
    "payment is pending",
)
_STRONG_CUSTOMER_PHRASES = (
    "wrong number", "galat number", "who are you", "who is speaking",
    "passed away", "my father", "my mother", "financial condition",
    "i will try", "give me some time", "i don't have funds", "i dont have funds",
    "main bol rah", "mera naam", "naukri nahi", "paisa nahi",
)
_BARE_ACK_RE = re.compile(r"^(yes|yeah|yep|okay|ok|haan ji|haan|ji|ho)[\s.,!]*$", re.I)


def _resegment_mixed_line(speaker: str, text: str) -> list[tuple[str, str]]:
    """Split one labeled turn into per-speaker segments when it mixes both speakers.

    Triggers only when a line carries strong cues from both sides, or a bare
    acknowledgment ("Yes.") is prefixed to clear agent content. Clean single-
    speaker lines are returned unchanged.
    """
    sentences = [s for s in re.split(r"(?<=[.!?])\s+", text) if s.strip()]
    if len(sentences) < 2:
        return [(speaker, text)]

    def _tag(sentence: str) -> str | None:
        low = sentence.lower()
        if any(p in low for p in _STRONG_AGENT_PHRASES):
            return "Agent"
        if any(p in low for p in _STRONG_CUSTOMER_PHRASES):
            return "Customer"
        return None

    tags = [_tag(s) for s in sentences]

    # Leading bare ack ("Yes.") merged onto agent content belongs to the customer.
    if _BARE_ACK_RE.match(sentences[0].strip()):
        rest_tag = next((t for t in tags[1:] if t), None)
        if rest_tag == "Agent":
            tags[0] = "Customer"

    if len({t for t in tags if t}) < 2:
        return [(speaker, text)]

    first_known = next((t for t in tags if t), speaker)
    resolved: list[tuple[str, str]] = []
    last = None
    for tag, sentence in zip(tags, sentences):
        current = tag or last or first_known
        resolved.append((current, sentence.strip()))
        last = current

    merged: list[tuple[str, str]] = []
    for sp, sentence in resolved:
        if not sentence:
            continue
        if merged and merged[-1][0] == sp:
            merged[-1] = (sp, f"{merged[-1][1]} {sentence}")
        else:
            merged.append((sp, sentence))
    return merged


def _repair_diarization(labelled: str) -> str:
    """Split merged Agent/Customer lines when both speakers appear in one block."""
    if not labelled:
        return labelled

    split_customer = re.compile(
        r"(?<=[.!?,])\s+(?="
        r"no\.?\s*who is speaking|who is speaking|the call got disconnected|"
        r"i am saying|i am now alone|because of that|i don'?t have funds|"
        r"i will give it|i will do it by|give it next month|next month|"
        r"customer:|tell me,?\s*by when|yes,?\s*tell me|"
        r"madam,?\s+i am saying|madam,?\s+my |madam,?\s+we are|sir,?\s+your app|"
        r"can you send|what do you want|change this number|wrong number|"
        r"like we deposit|what is not available|my father|my mother|passed away)",
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

        for seg_speaker, seg_text in _resegment_mixed_line(speaker, text):
            if len(seg_text) < 45:
                repaired.append(f"{seg_speaker}: {seg_text}")
                continue

            parts = (
                split_customer.split(seg_text)
                if seg_speaker == "Agent"
                else split_agent.split(seg_text)
            )
            if len(parts) <= 1:
                repaired.append(f"{seg_speaker}: {seg_text}")
                continue

            repaired.append(f"{seg_speaker}: {parts[0].strip()}")
            alt = "Customer" if seg_speaker == "Agent" else "Agent"
            for part in parts[1:]:
                part = part.strip()
                if part:
                    repaired.append(f"{alt}: {part}")

    return "\n".join(repaired)


def _classify_speaker_line(text: str) -> str:
    """Score-based Agent vs Customer — fixes LLM mis-tags on mixed Hindi/English calls."""
    low = (text or "").lower().strip()
    if not low:
        return "Agent"

    agent_score = 0
    customer_score = 0

    strong_customer = (
        "yes, tell me", "yes tell me", "yes, speaking", "yes speaking", "tell me",
        "wrong number", "galat number", "who is speaking", "who are you",
        "i am saying", "main bol rahi", "main bol raha", "mera naam",
        "my father", "my mother", "passed away", "expired", "died", "death",
        "financial condition", "paisa nahi", "paise nahi", "naukri nahi",
        "not him", "not her", "he is not here", "she is not here", "ghar pe nahi",
        "call got disconnected", "what do you want", "change this number",
        "i get calls day and night", "this is the wrong number",
        "i am now alone", "don't have funds", "dont have funds", "do not have funds",
        "no funds", "because of that", "unable to pay", "cannot pay", "can't pay",
        "not saying that you are wrong", "sim that i was using",
        "okay madam", "okay sir", "ok madam", "ok sir", "i will try", "won't happen",
        "wont happen", "not possible", "work is done", "money was spent",
    )
    strong_agent = (
        "speaking on behalf", "calling from", "on behalf of", "this call is recorded",
        "call is being recorded", "recorded for quality", "am i speaking with",
        "may i speak with", "speaking with", "your emi", "loan amount", "outstanding",
        "overdue", "payment due", "payment is pending", "from tala", "tala app",
        "collections", "recovery team", "please pay", "amount due", "dpd",
        "noted your ptp", "i will record", "disclaimer", "you have to pay",
        "don't try", "dont try", "from the ", "right?", "messages even before",
    )

    for p in strong_customer:
        if p in low:
            customer_score += 6
    for p in strong_agent:
        if p in low:
            agent_score += 6

    if re.search(r"^(yes|haan|ji|ho)[,.]?\s*(tell me|speaking|boliye|bolo)?\s*$", low):
        customer_score += 10
    if re.search(r"^(yes|no|okay|ok)\.?$", low):
        customer_score += 12
    if re.search(r"\b\w+(?:\s+\w+){0,3}\s+speaking\.?$", low) and "on behalf" not in low:
        customer_score += 14
    if re.search(r"\b(madam|sir),?\s+i am saying\b", low):
        customer_score += 10
    if re.search(r"\bmy (father|mother|wife|husband|papa|mummy)\b", low) and any(
        w in low for w in ("passed", "expired", "died", "death", "hospital", "trouble", "bad")
    ):
        customer_score += 12
    if re.search(r"\b(speaking on behalf|calling from|on behalf of)\b", low):
        agent_score += 10
    if re.search(r"\b(this is|i am)\s+[a-z][a-z'-]+\s+(?:from|with|of|at)\b", low):
        agent_score += 10
    elif re.search(
        r"\b(this is|i am)\s+[a-z][a-z'-]+\s+speaking\b",
        low,
    ) and any(x in low for x in ("from", "behalf", "collections", "tala", "calling", "company")):
        agent_score += 8
    if re.search(r"\b(please pay|pay (today|tomorrow|by)|your (emi|loan|dues))\b", low):
        agent_score += 8
    if re.search(r"\b(wrong number|galat number)\b", low):
        customer_score += 10
    if re.search(r"\b(i will try|won't happen|wont happen|work is done)\b", low):
        customer_score += 12
    if re.search(r"\b(don't try|dont try|you have to pay|from the \d{1,2})\b", low):
        agent_score += 12
    if re.search(r"\b(i will give|give it|next month|by the \d|don't have funds|dont have funds|i am now alone)\b", low):
        customer_score += 8
    if re.search(r"\b(bolte|bol rahe|bol rahi|speaking)\b.*\?", low):
        agent_score += 6
    if low.endswith("?") and any(w in low for w in ("who", "what", "why", "kaun", "kya")):
        customer_score += 3

    if customer_score > agent_score + 2:
        return "Customer"
    if agent_score > customer_score + 2:
        return "Agent"
    return ""


def _post_correct_speakers(labelled: str) -> tuple[str, list[dict]]:
    """Post-pass: re-label lines where content clearly belongs to the other speaker."""
    if not labelled:
        return labelled, []
    corrected: list[str] = []
    log: list[dict] = []
    prev = ""
    for raw in labelled.splitlines():
        line = raw.strip()
        m = re.match(r"^(agent|customer)\s*:\s*(.*)$", line, re.I)
        if not m:
            continue
        current = m.group(1).title()
        text = (m.group(2) or "").strip()
        inferred = _classify_speaker_line(text)
        if not inferred and prev == "Agent":
            if re.match(r"^(yes|no|okay|ok)\b", text, re.I):
                inferred = "Customer"
        if inferred and inferred != current:
            log.append({"from": current, "to": inferred, "text": text[:120]})
            current = inferred
        if _is_meta_or_noise_line(text):
            continue
        corrected.append(f"{current}: {text}")
        prev = current
    return "\n".join(corrected), log


def _fix_monologue_speakers(labelled: str, log: list[dict]) -> str:
    """Re-classify when almost every line is tagged as one speaker."""
    lines = [ln.strip() for ln in (labelled or "").splitlines() if ln.strip()]
    if len(lines) < 4:
        return labelled
    agent_n = sum(1 for ln in lines if re.match(r"^agent\s*:", ln, re.I))
    ratio = agent_n / len(lines)
    if ratio < 0.85 and ratio > 0.15:
        return labelled

    dominant = "Agent" if ratio >= 0.85 else "Customer"
    alt = "Customer" if dominant == "Agent" else "Agent"
    fixed: list[str] = []
    for raw in lines:
        m = re.match(r"^(agent|customer)\s*:\s*(.*)$", raw, re.I)
        if not m:
            fixed.append(raw)
            continue
        text = (m.group(2) or "").strip()
        inferred = _classify_speaker_line(text)
        speaker = inferred if inferred else (alt if m.group(1).title() == dominant else m.group(1).title())
        if speaker != m.group(1).title():
            log.append({"from": m.group(1).title(), "to": speaker, "text": text[:120], "reason": "monologue_fix"})
        fixed.append(f"{speaker}: {text}")
    return "\n".join(fixed)


def format_labelled_transcript(text: str, speaker_turns_out: list | None = None) -> str:
    """Keep only Agent:/Customer: lines — safe for UI and scoring storage.

    When `speaker_turns_out` is provided it is filled with the canonical verified
    turns (speaker/confidence/reason/changed) from the attribution layer.
    """
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
        labelled = _filter_labelled_lines("\n".join(lines))
        repaired = _repair_diarization(labelled)
        # Canonical text fallback when audio diarization is unavailable.
        # It provides confidence + reason, but hard validation prevents
        # text-only all-Agent output from being auto-approved.
        turns = attribute_transcript(repaired)
        out = to_labelled_text(turns)
        n_corr = sum(1 for t in turns if t.get("changed"))
        if n_corr:
            print(f"[SPEAKER] corrections={n_corr}/{len(turns)} lines", flush=True)
        if speaker_turns_out is not None:
            speaker_turns_out.clear()
            speaker_turns_out.extend(turns)
        return out
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
    """Agent/Customer bifurcation — LLM first, heuristic fallback if incomplete."""
    raw_text = re.sub(r"\s+", " ", (raw_text or "")).strip()
    if not raw_text:
        return "", ""
    labelled = ""
    try:
        agent, labelled = _diarize_with_llm(raw_text, api_key)
        labelled = _filter_labelled_lines(format_labelled_transcript(labelled) or labelled)
        coverage = _word_coverage(raw_text, labelled)
        print(f"[BIFURCATION] LLM coverage={coverage:.0%} raw={len(raw_text)} labelled={len(labelled)}", flush=True)
        if labelled and _transcript_has_dialogue(labelled) and coverage >= DIARIZATION_MIN_COVERAGE:
            agent = agent or "\n".join(
                ln for ln in labelled.splitlines() if ln.strip().lower().startswith("agent:")
            )
            return agent, labelled
        print(
            f"[BIFURCATION] LLM incomplete (coverage {coverage:.0%} < {DIARIZATION_MIN_COVERAGE:.0%}) — heuristic",
            flush=True,
        )
    except Exception as exc:
        print(f"[BIFURCATION] LLM failed or contaminated, using heuristic: {exc}", flush=True)
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
- Agent = company/collector from Tala/bank/collections. Customer = borrower or person answering the phone.
- Customer lines include: yes tell me, hardship (father died, no money), wrong number, who are you, objections.
- Agent lines include: recorded disclaimer, speaking on behalf, loan/EMI/outstanding, payment requests, RPC questions.
- If customer explains personal hardship (death, job loss, medical), label as Customer even if they say "Madam/Sir" first.
- Alternate turns when speakers change.
- Do NOT include reasoning, planning, notes, or XML tags.
- Do NOT summarize or skip lines. Include the FULL call from the very first word (hello/good morning/disclaimer) through closing.
- NEVER start from the middle. If the raw transcript begins with a greeting or name confirmation, that MUST be the first lines.
- Preserve exact payment amounts, dates, loan details, objections, Hindi/English mix, and compliance disclosures.
- If unsure who spoke, infer from context (questions about payment = often Agent; hardship/PTP promises = Customer).

RAW TRANSCRIPT:
{raw_transcript[:12000]}
""".strip()
    r = requests.post(
        "https://api.sarvam.ai/v1/chat/completions",
        headers={"Authorization": "Bearer " + api_key, "Content-Type": "application/json"},
        json={
            "model": os.getenv("SARVAM_CHAT_MODEL", "sarvam-30b"),
            "messages": [
                {"role": "system", "content": "You label call transcripts. Output ONLY Agent: and Customer: lines. Never output thinking or notes."},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.0,
            "max_tokens": 4096,
        },
        timeout=120,
    )
    if r.status_code != 200:
        raise RuntimeError(f"Diarization LLM {r.status_code}: {r.text[:200]}")
    labelled = _filter_labelled_lines(format_labelled_transcript(r.json()["choices"][0]["message"]["content"]))
    if not labelled or not _transcript_has_dialogue(labelled):
        raise ValueError("LLM diarization returned no usable dialogue (meta/reasoning filtered)")
    agent = "\n".join(line.strip() for line in labelled.splitlines() if line.strip().lower().startswith("agent:"))
    return agent or labelled, labelled


def transcribe(audio_path):
    key = os.getenv("SARVAM_API_KEY")
    if not key:
        raise EnvironmentError("SARVAM_API_KEY not set")

    mb = os.path.getsize(audio_path) / 1024 / 1024
    print(f"[STT] {os.path.basename(audio_path)} ({round(mb, 1)} MB)", flush=True)

    from diarization import CARE_USE_DIARIZATION, DiarizationFailedError, diarize_audio
    from speaker_attribution import to_labelled_text

    if CARE_USE_DIARIZATION:
        try:
            diar_turns = diarize_audio(audio_path)
        except DiarizationFailedError:
            raise
        except Exception as exc:
            raise DiarizationFailedError(f"Sarvam diarization error: {exc}") from exc
        if not diar_turns:
            raise DiarizationFailedError(
                "Sarvam diarization returned no speaker segments. "
                "Check SARVAM_API_KEY, audio format, and Sarvam job status."
            )
        labelled = to_labelled_text(diar_turns)
        agent_transcript = "\n".join(
            f"Agent: {t['text']}" for t in diar_turns if t.get("speaker") == "Agent"
        )
        print(
            f"[STT] diarized transcript: {len(diar_turns)} turns "
            f"({sum(1 for t in diar_turns if t.get('speaker') == 'Agent')} agent / "
            f"{sum(1 for t in diar_turns if t.get('speaker') == 'Customer')} customer)",
            flush=True,
        )
        return agent_transcript, labelled, diar_turns

    # Legacy path only when CARE_USE_DIARIZATION=0.
    try:
        chunks, tmpdir = split_audio(audio_path)
    except FileNotFoundError as exc:
        print(f"[STT] ffmpeg error ({exc}) — full-file transcription", flush=True)
        chunks, tmpdir = [audio_path], None
    try:
        results: dict[int, str] = {}
        if len(chunks) == 1:
            i, raw_text = _transcribe_chunk(chunks[0], key, 0)
            results[i] = raw_text
        else:
            with ThreadPoolExecutor(max_workers=min(3, len(chunks))) as ex:
                futs = {ex.submit(_transcribe_chunk, c, key, i): i for i, c in enumerate(chunks)}
                for f in as_completed(futs):
                    i, t = f.result()
                    results[i] = t
            raw_text = _merge_chunk_transcripts(results)
        raw_text = re.sub(r"\s+", " ", raw_text or "").strip()
        empty = sum(1 for i in range(len(chunks)) if not (results.get(i) or "").strip())
        if len(chunks) > 1 and empty > 0:
            print(f"[STT] WARNING: {empty}/{len(chunks)} chunks returned empty — transcript may be incomplete", flush=True)
        print(f"[STT] Raw done {len(raw_text)} chars from {len(chunks)} chunk(s)", flush=True)
        # Raw STT output BEFORE any speaker reconstruction. Sarvam's
        # speech-to-text-translate returns plain text with NO speaker labels,
        # so everything downstream is reconstructed — log it to make that visible.
        safe_preview = (raw_text[:800] or "").encode("ascii", errors="replace").decode("ascii")
        print(f"[STT][RAW] {safe_preview}", flush=True)
        if len(raw_text) < 4:
            raise RuntimeError(
                "No speech detected from audio. Check recording quality/codec (try wav/mp3) or verify file is valid audio."
            )

        from scoring_rules import cleanup_transcript_for_scoring, sanitize_transcript

        agent_transcript, labelled = bifurcate_transcript(raw_text, key)
        before_len = len(labelled or "")
        labelled = sanitize_transcript(format_labelled_transcript(labelled) or labelled)
        labelled = cleanup_transcript_for_scoring(labelled)
        after_len = len(labelled or "")
        print(f"[SANITIZE] transcript {before_len} -> {after_len} chars", flush=True)
        agent_transcript = agent_transcript or "\n".join(
            ln for ln in labelled.splitlines() if ln.strip().lower().startswith("agent:")
        )
        agent_transcript = sanitize_transcript(agent_transcript) or agent_transcript
        print(
            f"[BIFURCATION] labelled {len(labelled)} chars | agent {len(agent_transcript)} chars",
            flush=True,
        )
        return agent_transcript, labelled, None
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
- 2 = opening disclosure (recording disclaimer OR on-behalf + call purpose) + agent intro + RPC + greeting/name
- 1 = most elements present, one missing (e.g. RPC weak or no greeting)
- 0 = no RPC on a collections call, or no intro on collections call

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
    text = re.sub(r"```json\s*", "", text, flags=re.I)
    text = re.sub(r"```\s*", "", text)
    text = re.sub(r"<think>[\s\S]*?</think>", "", text, flags=re.I)
    # Prefer outermost object
    match = re.search(r"\{[\s\S]*\}", text)
    if not match:
        return ""
    js = match.group(0)
    js = re.sub(r",(\s*[}\]])", r"\1", js)
    return js.strip()


def _parse_scoring_json(raw: str) -> dict | None:
    """Extract and validate scoring JSON from LLM output."""
    if not raw:
        return None
    candidates = [raw]
    cleaned = _clean_json(raw)
    if cleaned and cleaned not in candidates:
        candidates.append(cleaned)
    # Sometimes model wraps JSON in an array
    arr_match = re.search(r"\[[\s\S]*\]", raw)
    if arr_match:
        candidates.append(arr_match.group(0))
    for cand in candidates:
        for attempt in (cand, _clean_json(cand)):
            if not attempt:
                continue
            try:
                data = json.loads(attempt)
            except Exception:
                continue
            if isinstance(data, list) and data and isinstance(data[0], dict):
                data = data[0]
            if not isinstance(data, dict):
                continue
            scores = data.get("scores")
            if isinstance(scores, dict) and scores:
                return data
            if data.get("summary") or data.get("total_score") is not None:
                return data
    return None


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


def _fallback_score(transcript, filename_hint: str = ""):
    """Rules-only scoring rescue — never used as transcript content."""
    from scoring_rules import build_rules_fallback_result
    return build_rules_fallback_result(transcript, filename_hint)


def _score_sales(labelled_transcript: str) -> dict:
    """Run the deterministic Sales QA engine and shape it for the call payload.

    Fully independent of the Collections pipeline (no shared scoring rules).
    """
    from audit_modes.sales_kpi import score_sales_call, validate_sales_audit

    audit = validate_sales_audit(labelled_transcript, score_sales_call(labelled_transcript))
    summary = audit.get("summary", {})
    intent = audit.get("customer_intent", "unknown")
    prob = audit.get("sales_probability", "low")
    disposition = "SALE_CLOSED" if prob == "high" else ("FOLLOW_UP" if prob == "medium" else "NOT_INTERESTED")

    return {
        "scoring_source": "sales_rules_engine",
        "total_score": round(audit.get("total_score", 0)),
        "total_score_pct": audit.get("total_pct", 0),
        "grade": audit.get("grade", "Poor"),
        "critical_fail": bool(audit.get("critical_fail", False)),
        "confidence": int(round(audit.get("avg_confidence", 0.6) * 100)),
        "disposition": disposition,
        "risk_level": "HIGH" if audit.get("critical_fail") else "LOW",
        "ai_detection": (["FATAL_ERROR"] if audit.get("critical_fail") else ["NONE"]),
        "ai_suggestion": (audit.get("recommendations") or [""])[0],
        "agent_sentiment": "neutral",
        "sentiment_notes": "",
        "summary": summary.get("executive_summary", ""),
        "key_issues": summary.get("missed_opportunities", []),
        "strengths": summary.get("strengths", []),
        "coaching_tip": (summary.get("coaching_suggestions") or [""])[0],
        "compliance_flags": (["FATAL_ERROR"] if audit.get("critical_fail") else ["NONE"]),
        "review_required": bool(audit.get("review_required", False)),
        # Full structured sales audit for the dedicated Sales panel.
        "sales_kpi": audit,
    }


def score_transcript(
    labelled_transcript,
    filename_hint: str = "",
    audit_mode: str | None = None,
    *,
    audio_diarized: bool = False,
):
    from audit_modes import get_scoring_prompt, max_score_for_mode, normalize_audit_mode

    mode = normalize_audit_mode(audit_mode)
    max_score = max_score_for_mode(mode)
    key = os.getenv("SARVAM_API_KEY")
    from scoring_rules import (
        cleanup_transcript_for_scoring,
        detect_call_kpis,
        resolve_disposition,
        run_hybrid_scoring,
        sanitize_transcript,
    )

    raw_len = len(labelled_transcript or "")
    if audio_diarized:
        # Turns already verified from Sarvam audio diarization — do not re-run text attribution.
        labelled_transcript = sanitize_transcript(labelled_transcript or "")
    else:
        labelled_transcript = sanitize_transcript(
            format_labelled_transcript(labelled_transcript) or labelled_transcript
        )
    labelled_transcript = cleanup_transcript_for_scoring(labelled_transcript)
    print(f"[SANITIZE] score input {raw_len} -> {len(labelled_transcript)} chars", flush=True)
    if not labelled_transcript.strip():
        raise ValueError("Empty transcript after cleanup")

    # --- Sales QA: completely separate deterministic engine (no Collections logic) ---
    if mode == "sales":
        return _score_sales(labelled_transcript)

    if not key:
        print("[SCORE] SARVAM_API_KEY not set — using rules_fallback (dev mode)", flush=True)
        result = _fallback_score(labelled_transcript, filename_hint)
        json_parsed = False
        scoring_source = "rules_fallback"
    else:
        kpis = detect_call_kpis(labelled_transcript, filename_hint=filename_hint)
        print(
            f"[KPI] rpc_confirmed={kpis.get('rpc_confirmed')} ptp_detected={bool(kpis.get('ptp_detected'))} "
            f"third_party={bool(kpis.get('third_party'))} dispositions={kpis.get('dispositions')}",
            flush=True,
        )

        prompt = get_scoring_prompt(mode).format(
            transcript=labelled_transcript[:10000],
            few_shot_block=_build_few_shot_block(labelled_transcript) if mode == "collections" else "",
        )

        def call_llm(messages, temp=0.0, max_tokens=1400):
            r = requests.post(
                "https://api.sarvam.ai/v1/chat/completions",
                headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"},
                json={
                    "model": os.getenv("SARVAM_CHAT_MODEL", "sarvam-30b"),
                    "messages": messages,
                    "temperature": temp,
                    "max_tokens": max_tokens,
                },
                timeout=90,
            )
            if r.status_code != 200:
                raise RuntimeError(f"Sarvam LLM {r.status_code}: {r.text[:300]}")
            payload = r.json()
            choices = payload.get("choices") or []
            content = ""
            if choices:
                content = (choices[0].get("message") or {}).get("content") or ""
            if not content:
                raise RuntimeError(f"Sarvam LLM empty response: {str(payload)[:200]}")
            return content

        use_rules_only = os.getenv("CARE_RULES_ONLY_SCORING", "").lower() in ("1", "true", "yes")
        raw = ""
        json_parsed = False
        scoring_source = "ai_json"
        if use_rules_only:
            print("[SCORE] CARE_RULES_ONLY_SCORING=1 — skipping LLM", flush=True)
            result = _fallback_score(labelled_transcript, filename_hint)
            json_parsed = False
            scoring_source = "rules_fallback"
        else:
            try:
                raw = call_llm([
                    {"role": "system", "content": "Output ONLY valid raw JSON. Start with { immediately. No markdown."},
                    {"role": "user", "content": prompt},
                ])
                print(f"[SCORE] Attempt 1 ({len(raw)} chars): {raw[:80]}", flush=True)
                parsed = _parse_scoring_json(raw)
                if not parsed:
                    raw2 = call_llm([
                        {"role": "system", "content": "Return ONLY a valid JSON object with keys: scores, summary, disposition. No markdown, no prose."},
                        {"role": "user", "content": prompt},
                        {"role": "assistant", "content": raw[:4000]},
                        {"role": "user", "content": "Your previous output was invalid JSON. Reply with ONLY the corrected JSON object starting with {."},
                    ], max_tokens=1600)
                    print(f"[SCORE] Attempt 2 ({len(raw2)} chars): {raw2[:80]}", flush=True)
                    parsed = _parse_scoring_json(raw2)
                if not parsed:
                    raw3 = call_llm([
                        {"role": "system", "content": '{"scores":{"A1_opening":0}} — respond with one JSON object only.'},
                        {"role": "user", "content": f"Score this call. Output JSON only:\n\n{labelled_transcript[:6000]}"},
                    ], temp=0.0, max_tokens=1200)
                    print(f"[SCORE] Attempt 3 strict ({len(raw3)} chars): {raw3[:80]}", flush=True)
                    parsed = _parse_scoring_json(raw3)
                if not parsed:
                    print("[SCORE] model JSON parsed=false after 3 attempts — using rules_fallback", flush=True)
                    result = _fallback_score(labelled_transcript, filename_hint)
                    json_parsed = False
                    scoring_source = "rules_fallback"
                else:
                    result = parsed
                    json_parsed = True
                    scoring_source = "ai_json"
            except Exception as exc:
                print(f"[SCORE] LLM failed ({exc}), model JSON parsed=false — using rules_fallback", flush=True)
                result = _fallback_score(labelled_transcript, filename_hint)
                json_parsed = False
                scoring_source = "rules_fallback"

    if not key:
        kpis = detect_call_kpis(labelled_transcript, filename_hint=filename_hint)

    print(f"[SCORE] model JSON parsed={json_parsed} scoring_source={scoring_source}", flush=True)

    scores = result.get("scores") or {}
    if mode == "sales":
        sk = result.get("sales_kpi") or {}
        try:
            perf = int(sk.get("agent_performance_score") or result.get("agent_performance_score") or 0)
        except Exception:
            perf = 0
        perf = max(0, min(10, perf))
        result["sales_kpi"] = sk
        result["scores"] = {"agent_performance_score": perf}
        fixed_scores = result["scores"]
    else:
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

    if scoring_source != "rules_fallback" and mode != "sales":
        result = run_hybrid_scoring(result, labelled_transcript, filename_hint)
    result["scoring_source"] = scoring_source
    result["audit_mode"] = mode

    fixed_scores = result["scores"]
    total = sum(fixed_scores.values())
    if "_scoring_calibration" not in result:
        result["total_score"] = total
        result["total_score_pct"] = int(round((total / max_score) * 100))
        if mode == "sales":
            try:
                perf = int((result.get("sales_kpi") or {}).get("agent_performance_score") or total)
            except Exception:
                perf = total
            result["grade"] = (
                "Excellent" if total >= 9 else "Good" if total >= 7
                else "Needs Improvement" if total >= 4 else "Poor"
            )
            result["critical_fail"] = perf <= 2
        else:
            result["grade"] = (
                "Excellent" if total >= 18 else "Good" if total >= 14
                else "Needs Improvement" if total >= 8 else "Poor"
            )
            critical = ["A3_probing", "A4_negotiation", "A5_commitment_ptp", "A7_professionalism"]
            result["critical_fail"] = bool(any(fixed_scores.get(k, 0) == 0 for k in critical))
    else:
        total = int(result.get("total_score") or total)

    if mode == "sales":
        disposition = str(result.get("disposition") or "OTHER").upper().replace(" ", "_")
        result["compliance_flags"] = [f for f in _as_list(result.get("compliance_flags")) if f != "NONE"] or []
        result["ai_detection"] = _as_list(result.get("ai_detection")) or ["NONE"]
        result["key_issues"] = _as_list(result.get("key_issues"))
        result["strengths"] = _as_list(result.get("strengths"))
        result["disposition"] = disposition
        result["risk_level"] = str(result.get("risk_level") or "LOW").upper()
        try:
            result["confidence"] = int(result.get("confidence") or 80)
        except Exception:
            result["confidence"] = 80
        print(
            f"[SCORE] FINAL sales disposition={disposition} score={total}/{max_score} ({result.get('grade')})",
            flush=True,
        )
        return result

    opening = result.get("opening_audit") or {}
    rpc_confirmed = bool(opening.get("rpc_confirmed") or kpis.get("rpc_confirmed"))
    ptp_detected = bool(result.get("ptp_detected") or kpis.get("ptp_detected"))
    disposition = str(result.get("disposition") or "OTHER").upper().replace(" ", "_")

    result["ptp_detected"] = ptp_detected
    result["compliance_flags"] = [f for f in _as_list(result.get("compliance_flags")) if f != "NONE"] or []
    result["ai_detection"] = _as_list(result.get("ai_detection")) or ["NONE"]
    result["key_issues"] = _as_list(result.get("key_issues"))
    result["strengths"] = _as_list(result.get("strengths"))
    result["disposition"] = disposition
    result["risk_level"] = str(result.get("risk_level") or "LOW").upper()

    # Keep opening_audit badges and key_issues / flags in sync (no RPC confirmed + RPC not confirmed).
    if rpc_confirmed:
        result["key_issues"] = [
            x for x in result["key_issues"]
            if "rpc" not in str(x).lower()
        ]
        result["ai_detection"] = [
            x for x in result["ai_detection"]
            if "RPC_MISSED" not in str(x).upper() and "RPC NOT" not in str(x).upper()
        ] or ["NONE"]
        result["compliance_flags"] = [
            f for f in result["compliance_flags"] if str(f).upper() != "RPC_MISSED"
        ]
    if ptp_detected:
        result["key_issues"] = [
            x for x in result["key_issues"]
            if "no valid ptp" not in str(x).lower() and str(x).strip().lower() not in {"no ptp", "no ptp secured"}
        ]
        result["compliance_flags"] = [
            f for f in result["compliance_flags"]
            if str(f).upper() not in {"NO_PTP"}
        ]
        if "PTP_DETECTED" not in [str(f).upper() for f in result["compliance_flags"]]:
            result["compliance_flags"].append("PTP_DETECTED")
        if disposition in {"", "OTHER", "CALLBACK"}:
            result["disposition"] = "PTP"
            disposition = "PTP"

    opening = result.get("opening_audit") or {}
    opening["rpc_confirmed"] = rpc_confirmed
    result["opening_audit"] = opening
    try:
        result["confidence"] = int(result.get("confidence") or 80)
    except Exception:
        result["confidence"] = 80

    print(
        f"[SCORE] FINAL rpc_confirmed={rpc_confirmed} ptp_detected={ptp_detected} "
        f"disposition={disposition} score={total}/{max_score} ({result.get('grade')})",
        flush=True,
    )
    # Authoritative disposition from rules — LLM cannot override hybrid pipeline.
    if mode != "sales":
        kpis_final = detect_call_kpis(labelled_transcript, filename_hint=filename_hint)
        result["disposition"] = resolve_disposition(labelled_transcript, kpis_final)
    return result


def _resolve_audit_mode(call_row: dict | None, metadata: dict | None = None) -> str:
    from audit_modes import normalize_audit_mode
    row = call_row or {}
    meta = metadata or {}
    analysis = row.get("analysis") or {}
    if isinstance(analysis, str):
        try:
            analysis = json.loads(analysis)
        except Exception:
            analysis = {}
    for src in (row, meta, analysis if isinstance(analysis, dict) else {}):
        mode = src.get("audit_mode") if isinstance(src, dict) else None
        if mode:
            return normalize_audit_mode(mode)
    campaign = str(row.get("campaign_id") or meta.get("campaign_id") or "").lower()
    if campaign.startswith("sales") or "sales" in campaign:
        return "sales"
    return normalize_audit_mode(None)


def process_call(call_id, audio_source, calls_db, update_call_fn):
    with _PROCESS_SEM:
        _process_call_inner(call_id, audio_source, calls_db, update_call_fn)


def _audio_source_for_call(row: dict) -> str:
    row = row or {}
    for key in ("file_path", "source_uri"):
        candidate = str(row.get(key) or "").strip()
        if candidate:
            return candidate
    return ""


def _analysis_dict(row: dict) -> dict:
    analysis = (row or {}).get("analysis") or {}
    if isinstance(analysis, str):
        try:
            return json.loads(analysis) if analysis.strip() else {}
        except Exception:
            return {}
    return dict(analysis) if isinstance(analysis, dict) else {}


def _process_call_inner(call_id, audio_source, calls_db, update_call_fn):
    from audit_pipeline import append_pipeline_log
    from diarization import DiarizationFailedError
    from scoring_rules import sanitize_transcript

    tmp = tempfile.mkdtemp(prefix="care_dl_")
    try:
        call_row = calls_db if isinstance(calls_db, dict) and calls_db.get("filename") else None
        if not call_row:
            try:
                from database import get_call
                call_row = get_call(call_id) or {}
            except Exception:
                call_row = {}

        append_pipeline_log(update_call_fn, call_id, "fetching_started", status="fetching")
        local = _resolve_processing_audio(call_id, audio_source, call_row, tmp)

        hint_name = (
            call_row.get("filename")
            or os.path.basename(str(local))
        )
        metadata = parse_filename_metadata(hint_name)
        if metadata.get("agent_id") in ("Unknown", "gdrive") and call_row.get("agent_id"):
            metadata["agent_id"] = call_row["agent_id"]
        if metadata.get("loan_id") in ("Unknown", "gdrive") and call_row.get("loan_id"):
            metadata["loan_id"] = call_row["loan_id"]
        _safe_update_call(update_call_fn, call_id, {"status": "transcribing", **metadata})
        append_pipeline_log(
            update_call_fn, call_id, "transcribing_started", status="transcribing",
            detail=f"agent={metadata.get('agent_id')} loan={metadata.get('loan_id')}",
        )
        print(f"[PIPELINE] {call_id} transcribing... metadata={metadata}", flush=True)

        agent_transcript, labelled_transcript, diarized_turns = transcribe(local)
        if not labelled_transcript.strip():
            err = "No labelled transcript generated. Recording may be silent/too short or unsupported."
            append_pipeline_log(update_call_fn, call_id, "transcribe_failed", status="failed", error=err)
            _safe_update_call(update_call_fn, call_id, {"status": "failed", "error": err})
            return

        speaker_turns: list = []
        if diarized_turns:
            from speaker_attribution import to_labelled_text

            speaker_turns = diarized_turns
            display_transcript = sanitize_transcript(to_labelled_text(diarized_turns))
        else:
            from diarization import CARE_USE_DIARIZATION

            if CARE_USE_DIARIZATION:
                raise DiarizationFailedError(
                    "Audio diarization is required but no diarized turns were produced."
                )
            display_transcript = sanitize_transcript(
                format_labelled_transcript(labelled_transcript, speaker_turns) or labelled_transcript
            )
            for t in speaker_turns:
                t.setdefault("attribution_source", "text_fallback")
        if not display_transcript.strip():
            err = "Transcript empty after sanitization (prompt leak or no dialogue)."
            append_pipeline_log(update_call_fn, call_id, "sanitize_failed", status="failed", error=err)
            _safe_update_call(update_call_fn, call_id, {"status": "failed", "error": err})
            return

        _safe_update_call(update_call_fn, call_id, {
            "transcript": display_transcript,
            "agent_transcript": agent_transcript,
            "status": "scoring",
            **metadata,
        })
        append_pipeline_log(
            update_call_fn, call_id, "scoring_started", status="scoring",
            detail=f"{len(display_transcript)} chars",
        )

        print(f"[PIPELINE] {call_id} scoring {len(display_transcript)} chars...", flush=True)
        source_name = hint_name or os.path.basename(str(local))
        audit_mode = _resolve_audit_mode(call_row, metadata)
        s = score_transcript(
            display_transcript,
            source_name,
            audit_mode=audit_mode,
            audio_diarized=bool(diarized_turns),
        )

        from qa_validation import build_evidence_summary, validate_collections_audit
        from speaker_attribution import summarize_attribution

        if audit_mode == "sales":
            _sales_review = bool(s.get("review_required", False))
            qa = {"qa_confidence": s.get("confidence", 80),
                  "review_required": _sales_review,
                  "qa_status": "REVIEW_REQUIRED" if _sales_review else "AUTO_APPROVED",
                  "corrections": {},
                  "validation_notes": (s.get("sales_kpi") or {}).get("review_reasons", []),
                  "verified_facts": {}}
        else:
            qa = validate_collections_audit(display_transcript, s, speaker_turns)
        for key, val in (qa.get("corrections") or {}).items():
            s[key] = val
        if audit_mode != "sales" and (
            qa.get("review_required") or "AI JSON unavailable" in str(s.get("summary") or "")
        ):
            s["summary"] = build_evidence_summary(display_transcript, s)
        s["confidence"] = qa.get("qa_confidence", s.get("confidence", 80))

        if audit_mode != "sales":
            from speaker_attribution import needs_audio_reprocess

            if needs_audio_reprocess(speaker_turns):
                raise DiarizationFailedError(
                    f"Untrusted speaker turns ({len(speaker_turns)} lines) — "
                    "refusing to save without audio_diarization."
                )

        max_pts = 10 if audit_mode == "sales" else 20
        total = int(s.get("total_score") or 0)
        pct = int(s.get("total_score_pct") or round((total / max_pts) * 100))

        payload = {
            "status": "processed",
            "transcript": display_transcript,
            "agent_transcript": agent_transcript,
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
            "dispositions": s.get("dispositions") or [s.get("disposition", "OTHER")],
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
                "scoring_source": s.get("scoring_source") or "ai_json",
                "audit_mode": audit_mode,
                "speaker_turns": speaker_turns if audit_mode != "sales" else [],
                "speaker_attribution": summarize_attribution(speaker_turns) if speaker_turns else {},
                "sales_kpi": s.get("sales_kpi") or {},
                "audio_reprocess_pending": False,
                "pipeline_error": None,
                "qa_validation": {
                    "status": qa.get("qa_status"),
                    "review_required": qa.get("review_required"),
                    "notes": qa.get("validation_notes") or [],
                    "verified_facts": qa.get("verified_facts") or {},
                    "speaker_attribution": qa.get("speaker_attribution") or {},
                },
            },
            **metadata,
        }
        _safe_update_call(update_call_fn, call_id, payload)
        append_pipeline_log(
            update_call_fn,
            call_id,
            "processed",
            status="processed",
            detail=f"score={total}/{max_pts} disposition={s.get('disposition')}",
        )

        if os.path.isfile(str(local)):
            playback_name = os.path.basename(str(local))
            upload_dir = os.path.join(os.path.dirname(__file__), "uploads")
            try:
                from storage import archive_local_audio, persist_playback_copy
                cached = persist_playback_copy(str(local), call_id, playback_name, upload_dir)
                playback_updates: dict = {}
                if cached:
                    playback_updates["file_path"] = cached
                elif os.path.isfile(str(local)):
                    playback_updates["file_path"] = str(local)
                s3_uri = archive_local_audio(str(local), call_id, playback_name)
                if s3_uri:
                    playback_updates["source_uri"] = s3_uri
                if playback_updates:
                    _safe_update_call(update_call_fn, call_id, playback_updates)
            except Exception as exc:
                print(f"[PIPELINE] Playback cache/S3 archive skipped: {exc}", flush=True)

        ptp = f"PTP: {s.get('ptp_amount')} on {s.get('ptp_date')}" if s.get("ptp_detected") else "No PTP"
        print(f"[PIPELINE] {call_id} DONE {total}/20 ({s.get('grade')}) | {s.get('disposition')} | {ptp}", flush=True)

    except DiarizationFailedError as e:
        err = str(e)
        append_pipeline_log(update_call_fn, call_id, "diarization_failed", status="diarization_failed", error=err)
        prev_analysis = _analysis_dict(call_row if isinstance(call_row, dict) else {})
        _safe_update_call(
            update_call_fn,
            call_id,
            {
                "status": "diarization_failed",
                "error": err,
                "analysis": {
                    **prev_analysis,
                    "pipeline_error": "DIARIZATION_FAILED",
                    "audio_reprocess_pending": False,
                    "qa_validation": {
                        "status": "REVIEW_REQUIRED",
                        "review_required": True,
                        "notes": [f"DIARIZATION_FAILED: {err}"],
                        "verified_facts": {},
                        "speaker_attribution": {},
                    },
                },
            },
        )
        print(f"[PIPELINE] {call_id} DIARIZATION_FAILED: {e}", flush=True)
    except json.JSONDecodeError as e:
        err = "Score parse error: " + str(e)
        append_pipeline_log(update_call_fn, call_id, "score_parse_failed", status="failed", error=err)
        _safe_update_call(update_call_fn, call_id, {"status": "failed", "error": err})
        print(f"[PIPELINE] {call_id} JSON error: {e}", flush=True)
    except Exception as e:
        append_pipeline_log(update_call_fn, call_id, "pipeline_error", status="failed", error=str(e))
        _safe_update_call(update_call_fn, call_id, {"status": "failed", "error": str(e)})
        print(f"[PIPELINE] {call_id} ERROR: {e}", flush=True)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def process_call_async(call_id, audio_source, calls_db, update_call_fn):
    t = threading.Thread(target=process_call, args=(call_id, audio_source, calls_db, update_call_fn), daemon=True)
    t.start()
    return t


_STUCK_STATUSES = ("queued", "fetching", "transcribing", "scoring", "processing")


def recover_stuck_calls(update_call_fn, max_age_minutes: int = 8) -> int:
    """
    Finish or retry calls left in mid-pipeline (e.g. after Flask reloader killed threads).
    Scoring + transcript present → re-score; queued with audio → re-queue; else mark failed.
    """
    try:
        from database import list_calls, get_call
        from audit_pipeline import append_pipeline_log
    except Exception as exc:
        print(f"[RECOVER] skipped: {exc}", flush=True)
        return 0

    cutoff = datetime.now(timezone.utc) - timedelta(minutes=max_age_minutes)
    recovered = 0
    for row in list_calls(limit=500):
        status = str(row.get("status") or "").lower()
        if status not in _STUCK_STATUSES:
            continue
        uploaded = row.get("uploaded_at") or row.get("created_at") or ""
        try:
            ts = datetime.fromisoformat(str(uploaded).replace("Z", "+00:00"))
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
        except Exception:
            ts = cutoff
        if ts > cutoff:
            continue
        call_id = row.get("id") or row.get("call_id")
        if not call_id:
            continue
        transcript = str(row.get("transcript") or "").strip()
        if status == "scoring" and transcript:
            print(f"[RECOVER] re-scoring stuck call {call_id}", flush=True)
            if reprocess_call_from_existing(call_id, get_call(call_id) or row, update_call_fn):
                recovered += 1
            continue

        audio = _audio_source_for_call(row)
        analysis = _analysis_dict(row)
        retries = int(analysis.get("pipeline_retries") or 0)
        if status in ("queued", "fetching", "transcribing") and audio and retries < _MAX_PIPELINE_RETRIES:
            print(f"[RECOVER] re-queueing {call_id} ({status}, retry {retries + 1})", flush=True)
            analysis["pipeline_retries"] = retries + 1
            append_pipeline_log(
                update_call_fn,
                call_id,
                "recover_retry",
                status="queued",
                detail=f"from={status} retry={retries + 1}",
            )
            _safe_update_call(
                update_call_fn,
                call_id,
                {"status": "queued", "analysis": analysis, "error": None},
            )
            process_call_async(call_id, audio, get_call(call_id) or row, update_call_fn)
            recovered += 1
            continue

        err = (
            f"Processing interrupted during {status}. "
            + (f"No audio source found. " if not audio else "")
            + "Re-upload the recording or use Reprocess if transcript exists."
        )
        print(f"[RECOVER] marking stuck call {call_id} failed ({status})", flush=True)
        append_pipeline_log(update_call_fn, call_id, "recover_failed", status="failed", error=err)
        _safe_update_call(update_call_fn, call_id, {"status": "failed", "error": err})
        recovered += 1
    if recovered:
        print(f"[RECOVER] handled {recovered} stuck call(s)", flush=True)
    return recovered


_AUDIO_REPROCESS_QUEUED: set[str] = set()
_AUDIO_REPROCESS_LOCK = threading.Lock()


def reprocess_call_from_audio(call_id: str, call_row: dict, update_call_fn) -> bool:
    """Re-transcribe from archived audio (Sarvam diarization) and replace transcript + analysis."""
    audio = _audio_source_for_call(call_row or {})
    if not audio:
        raise RuntimeError("No audio source — cannot reprocess from audio.")

    row = dict(call_row or {})
    analysis = _analysis_dict(row)
    analysis["audio_reprocess_pending"] = True
    _safe_update_call(
        update_call_fn,
        call_id,
        {"status": "transcribing", "error": None, "analysis": analysis},
    )
    print(f"[REPROCESS-AUDIO] {call_id} starting from {audio}", flush=True)
    process_call(call_id, audio, row, update_call_fn)
    try:
        from database import get_call
        updated = get_call(call_id) or {}
    except Exception:
        updated = {}
    ok = str(updated.get("status") or "").lower() == "processed"
    print(f"[REPROCESS-AUDIO] {call_id} done ok={ok} status={updated.get('status')}", flush=True)
    return ok


def queue_audio_reprocess_if_needed(call_id: str, call_row: dict, update_call_fn) -> bool:
    """Queue background audio re-diarization when stored speaker_turns are legacy/bad."""
    from diarization import CARE_USE_DIARIZATION
    from speaker_attribution import needs_audio_reprocess

    if not CARE_USE_DIARIZATION or not call_id:
        return False

    analysis = _analysis_dict(call_row)
    if analysis.get("audio_reprocess_pending"):
        return True

    speaker_turns = analysis.get("speaker_turns") or []
    if not needs_audio_reprocess(speaker_turns):
        return False

    audio = _audio_source_for_call(call_row)
    if not audio:
        return False
    if not str(audio).startswith("s3://") and not os.path.isfile(str(audio)):
        return False

    with _AUDIO_REPROCESS_LOCK:
        if call_id in _AUDIO_REPROCESS_QUEUED:
            return True
        _AUDIO_REPROCESS_QUEUED.add(call_id)

    analysis = dict(analysis)
    analysis["audio_reprocess_pending"] = True
    _safe_update_call(update_call_fn, call_id, {"analysis": analysis})

    def _run():
        try:
            from database import get_call
            row = get_call(call_id) or call_row
            reprocess_call_from_audio(call_id, row, update_call_fn)
        except Exception as exc:
            print(f"[REPROCESS-AUDIO] {call_id} failed: {exc}", flush=True)
        finally:
            with _AUDIO_REPROCESS_LOCK:
                _AUDIO_REPROCESS_QUEUED.discard(call_id)

    threading.Thread(
        target=_run, daemon=True, name=f"reprocess-audio-{call_id}",
    ).start()
    print(f"[REPROCESS-AUDIO] queued {call_id}", flush=True)
    return True


def reprocess_call_from_existing(call_id, call_row, update_call_fn):
    """
    Re-score and re-tag an already processed call using stored transcript + filename.
    Avoids re-downloading audio and is safe for bulk backfill jobs.
    """
    try:
        from scoring_rules import sanitize_transcript

        transcript = str((call_row or {}).get("transcript") or "").strip()
        if not transcript:
            raise RuntimeError("Transcript missing; cannot reprocess without stored dialogue.")

        before_len = len(transcript)
        labelled = sanitize_transcript(format_labelled_transcript(transcript) or transcript)
        print(f"[REPROCESS] {call_id} sanitize {before_len} -> {len(labelled)} chars", flush=True)
        if not labelled.strip():
            raise RuntimeError(
                "Transcript empty after sanitization — likely prompt leak; re-transcribe from audio."
            )

        source_name = (
            (call_row or {}).get("filename")
            or (call_row or {}).get("file_path")
            or (call_row or {}).get("source_uri")
            or ""
        )
        metadata = parse_filename_metadata(source_name)
        audit_mode = _resolve_audit_mode(call_row, metadata)
        s = score_transcript(labelled, source_name, audit_mode=audit_mode)
        max_pts = 10 if audit_mode == "sales" else 20
        total = int(s.get("total_score") or 0)
        pct = int(s.get("total_score_pct") or round((total / max_pts) * 100))

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
                "customer_issues": s.get("customer_issues") or [],
                "scoring_source": s.get("scoring_source") or "ai_json",
                "audit_mode": audit_mode,
                "sales_kpi": s.get("sales_kpi") or {},
                "qa_validation": {
                    "status": "REVIEW_REQUIRED" if s.get("review_required") else "AUTO_APPROVED",
                    "review_required": bool(s.get("review_required", False)),
                    "notes": (s.get("sales_kpi") or {}).get("review_reasons", []),
                },
                "reprocessed": True,
            },
            **metadata,
        }
        _safe_update_call(update_call_fn, call_id, payload)
        print(f"[REPROCESS] {call_id} done {total}/{max_pts} ({s.get('grade')})", flush=True)
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
    from client_display import (
        COLLECTIONS_KPI_KEYS,
        _NATIVE_MAX,
        collections_csv_headers,
        kpi_mask_names,
        scale_kpi_score,
    )

    kpi_headers = collections_csv_headers()
    output = io.StringIO()
    headers = [
        "id", "filename", "agent_id", "loan_id", "status", "score", "score_pct", "grade",
        "critical_fail", "ptp_detected", "ptp_amount", "ptp_date", "ptp_mode",
        "disposition", "risk_level", "ai_detection", "ai_suggestion", "confidence",
        "compliance_flags", "agent_sentiment",
    ] + kpi_headers + [
        "summary", "key_issues", "strengths", "coaching_tip", "uploaded_at", "processed_at",
    ]
    writer = csv.DictWriter(output, fieldnames=headers, extrasaction="ignore")
    writer.writeheader()
    for c in calls or []:
        bd = c.get("scores_breakdown") or {}
        row = {
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
            "summary": c.get("summary", ""),
            "key_issues": "; ".join(_as_list(c.get("key_issues"))),
            "strengths": "; ".join(_as_list(c.get("strengths"))),
            "coaching_tip": c.get("coaching_tip", ""),
            "uploaded_at": c.get("uploaded_at", ""),
            "processed_at": c.get("processed_at", ""),
        }
        for i, key in enumerate(COLLECTIONS_KPI_KEYS):
            native_max = _NATIVE_MAX[key]
            raw = bd.get(key, "")
            if raw != "" and kpi_mask_names():
                disp_score, disp_max = scale_kpi_score(raw, native_max)
                row[kpi_headers[i]] = f"{disp_score}/{disp_max}"
            else:
                row[kpi_headers[i]] = bd.get(key, "")
        writer.writerow(row)
    return output.getvalue().encode("utf-8-sig")
