"""
CARE Processing Pipeline v8 - Clean
"""

import os, json, re, threading, tempfile, shutil, subprocess
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import requests

CHUNK_SECONDS = 25


# ════════════════════════════════════
#  SOURCE CONNECTORS
# ════════════════════════════════════

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

    print(f"[GDRIVE] File ID: {file_id}")
    dl = "https://drive.google.com/uc?export=download&id=" + file_id + "&confirm=t"
    s = requests.Session()
    s.headers.update({"User-Agent": "Mozilla/5.0"})
    r = s.get(dl, stream=True, timeout=120)

    for k, v in r.cookies.items():
        if "download_warning" in k or "confirm" in k.lower():
            r = s.get(dl + "&confirm=" + v, stream=True, timeout=120)
            break

    dest = os.path.join(dest_dir, "gdrive_" + file_id + ".mp3")
    total = 0
    with open(dest, "wb") as f:
        for chunk in r.iter_content(32768):
            if chunk:
                f.write(chunk)
                total += len(chunk)

    if total < 1000:
        raise RuntimeError(
            "Google Drive download failed — only " + str(total) + " bytes. "
            "Make sure file is shared as 'Anyone with link can view'."
        )
    print("[GDRIVE] Done " + str(total // 1024) + "KB")
    return dest


def fetch_from_url(url, dest_dir):
    fname = url.split("/")[-1].split("?")[0] or "audio.mp3"
    if not any(fname.lower().endswith(x) for x in [".mp3",".wav",".m4a",".ogg",".flac",".aac",".wma"]):
        fname += ".mp3"
    dest = os.path.join(dest_dir, fname)
    print("[URL] Downloading " + url)
    r = requests.get(url, stream=True, timeout=120)
    r.raise_for_status()
    with open(dest, "wb") as f:
        for chunk in r.iter_content(32768):
            if chunk:
                f.write(chunk)
    print("[URL] Done " + str(os.path.getsize(dest) // 1024) + "KB")
    return dest


def fetch_from_s3(s3_uri, dest_dir):
    try:
        import boto3
    except ImportError:
        raise ImportError("Run: pip install boto3")
    uri = s3_uri.replace("s3://", "")
    bucket, key = uri.split("/", 1)
    dest = os.path.join(dest_dir, os.path.basename(key))
    print("[S3] Downloading s3://" + bucket + "/" + key)
    boto3.client(
        "s3",
        region_name=os.getenv("AWS_REGION", "eu-north-1"),
        aws_access_key_id=os.getenv("AWS_ACCESS_KEY_ID"),
        aws_secret_access_key=os.getenv("AWS_SECRET_ACCESS_KEY"),
    ).download_file(bucket, key, dest)
    print("[S3] Done " + str(os.path.getsize(dest) // 1024) + "KB")
    return dest


def resolve_audio_source(source, dest_dir):
    if source.startswith("s3://"):
        return fetch_from_s3(source, dest_dir)
    if "drive.google.com" in source:
        return fetch_from_google_drive(source, dest_dir)
    if source.startswith("http://") or source.startswith("https://"):
        return fetch_from_url(source, dest_dir)
    return source


# ════════════════════════════════════
#  AUDIO CHUNKING
# ════════════════════════════════════

def split_audio(path, chunk_sec=CHUNK_SECONDS):
    tmpdir = tempfile.mkdtemp(prefix="care_chunks_")
    pattern = os.path.join(tmpdir, "chunk_%04d.mp3")
    r = subprocess.run(
        ["ffmpeg", "-i", path, "-f", "segment",
         "-segment_time", str(chunk_sec), "-c:a", "libmp3lame",
         "-q:a", "4", "-y", pattern],
        capture_output=True, text=True
    )
    if r.returncode != 0:
        print("[CHUNK] ffmpeg unavailable — single file mode")
        shutil.rmtree(tmpdir, ignore_errors=True)
        return [path], None
    chunks = sorted([os.path.join(tmpdir, f) for f in os.listdir(tmpdir) if f.startswith("chunk_")])
    if not chunks:
        shutil.rmtree(tmpdir, ignore_errors=True)
        return [path], None
    print("[CHUNK] " + str(len(chunks)) + " chunks of " + str(chunk_sec) + "s")
    return chunks, tmpdir


# ════════════════════════════════════
#  TRANSCRIPTION
# ════════════════════════════════════

def _transcribe_chunk(chunk_path, api_key, idx):
    with open(chunk_path, "rb") as f:
        data = f.read()
    r = requests.post(
        "https://api.sarvam.ai/speech-to-text-translate",
        headers={"api-subscription-key": api_key},
        files={"file": (os.path.basename(chunk_path), data, "audio/mpeg")},
        data={"model": "saaras:v3", "language_code": "unknown", "target_language_code": "en-IN"},
        timeout=60,
    )
    if r.status_code != 200:
        print("[CHUNK " + str(idx) + "] Error " + str(r.status_code))
        return idx, ""
    text = r.json().get("transcript", "").strip()
    print("[CHUNK " + str(idx) + "] " + str(len(text)) + " chars")
    return idx, text


def _extract_agent_only(full_transcript):
    lines = full_transcript.split("\n")
    agent_lines = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        upper = line.upper()
        if any(upper.startswith(p) for p in ["CUSTOMER:", "CUSTOMER :", "CALLER:", "CLIENT:", "BORROWER:"]):
            continue
        agent_lines.append(line)
    agent = "\n".join(agent_lines) if agent_lines else full_transcript
    print("[BIFURCATION] Full: " + str(len(full_transcript)) + " | Agent: " + str(len(agent)) + " chars")
    return agent, full_transcript


def transcribe(audio_path):
    key = os.getenv("SARVAM_API_KEY")
    if not key:
        raise EnvironmentError("SARVAM_API_KEY not set")
    mb = os.path.getsize(audio_path) / 1024 / 1024
    print("[STT] " + os.path.basename(audio_path) + " (" + str(round(mb, 1)) + " MB)")
    chunks, tmpdir = split_audio(audio_path)
    try:
        if len(chunks) == 1:
            _, text = _transcribe_chunk(chunks[0], key, 0)
        else:
            results = {}
            with ThreadPoolExecutor(max_workers=min(8, len(chunks))) as ex:
                futs = {ex.submit(_transcribe_chunk, c, key, i): i for i, c in enumerate(chunks)}
                for f in as_completed(futs):
                    i, t = f.result()
                    results[i] = t
            text = " ".join(results[i] for i in sorted(results))
        print("[STT] Done " + str(len(text)) + " chars")
        return _extract_agent_only(text)
    finally:
        if tmpdir:
            shutil.rmtree(tmpdir, ignore_errors=True)


# ════════════════════════════════════
#  SCORING
# ════════════════════════════════════

SCORING_PROMPT = """You are a QA auditor for Company Finance collections call centre.
Score ONLY the AGENT. Output ONLY raw JSON starting with {{ - no thinking, no explanation.

FRAMEWORK (20 pts total):
A1 Opening (0-2): disclaimer + company name + customer name + RPC confirmed
A2 Case Knowledge (0-2): exact amount + DPD days + loan details stated
A3 Probing (0-3) CRITICAL: deep follow-up, asked for proof if excuse given
A4 Negotiation (0-3) CRITICAL: urgency + consequences + part payment offered
A5 PTP Commitment (0-3) CRITICAL: amount + date + payment mode all confirmed
A6 Closing (0-2): summarised PTP + professional close
A7 Professionalism (0-3) CRITICAL: no threats, no abuse, calm and empathetic
A8 Call Handling (0-1): controlled conversation flow
A9 Troubleshooting (0-1): resolved payment technical issues

FLAGS: THREAT|ABUSE|FALSE_PROMISE|WRONG_DISCLOSURE|PTP_DETECTED|NO_PTP|NONE

AGENT TRANSCRIPT:
{transcript}

JSON output (start with {{ immediately):
{{"scores":{{"A1_opening":0,"A2_case_knowledge":0,"A3_probing":0,"A4_negotiation":0,"A5_commitment_ptp":0,"A6_closing":0,"A7_professionalism":0,"A8_call_handling":0,"A9_troubleshooting":0}},"total_score":0,"total_score_pct":0,"grade":"Poor","critical_fail":false,"ptp_detected":false,"ptp_amount":null,"ptp_date":null,"ptp_mode":null,"agent_sentiment":"neutral","sentiment_notes":"brief note","compliance_flags":["NONE"],"summary":"2-3 sentence summary","key_issues":["issue1"],"strengths":["strength1"],"coaching_tip":"one specific tip"}}"""


def _clean_json(raw):
    if not raw:
        return ""

    text = raw.strip()

    # Remove markdown
    text = re.sub(r"```json", "", text, flags=re.IGNORECASE)
    text = re.sub(r"```", "", text)

    # Remove COMPLETE think blocks
    text = re.sub(
        r"<think>[\s\S]*?</think>",
        "",
        text,
        flags=re.IGNORECASE
    )

    # Extract JSON normally
    match = re.search(r"\{[\s\S]*\}", text)
    if match:
        js = match.group(0)
        js = re.sub(r",(\s*[}\]])", r"\1", js)
        return js.strip()

    # BROKEN THINK BLOCK FIX
    # Model outputs <think> but never closes it
    if "<think>" in raw.lower():

        think_part = raw.split("<think>", 1)[1]

        # Try extracting JSON from think block itself
        match = re.search(r"\{[\s\S]*\}", think_part)

        if match:
            js = match.group(0)
            js = re.sub(r",(\s*[}\]])", r"\1", js)
            return js.strip()

        # Fallback minimal JSON
        fallback = {
            "scores": {
                "A1_opening": 0,
                "A2_case_knowledge": 0,
                "A3_probing": 0,
                "A4_negotiation": 0,
                "A5_commitment_ptp": 0,
                "A6_closing": 0,
                "A7_professionalism": 0,
                "A8_call_handling": 0,
                "A9_troubleshooting": 0
            },
            "total_score": 0,
            "total_score_pct": 0,
            "grade": "Poor",
            "critical_fail": False,
            "ptp_detected": False,
            "ptp_amount": None,
            "ptp_date": None,
            "ptp_mode": None,
            "agent_sentiment": "neutral",
            "sentiment_notes": "",
            "compliance_flags": ["NONE"],
            "summary": think_part[:400],
            "key_issues": [],
            "strengths": [],
            "coaching_tip": ""
        }
        return json.dumps(fallback)



def _is_valid_json(text):
    try:
        json.loads(text)
        return True
    except Exception:
        return False


def score_transcript(agent_transcript):
    key = os.getenv("SARVAM_API_KEY")
    if not key:
        raise EnvironmentError("SARVAM_API_KEY not set")

    prompt = SCORING_PROMPT.format(transcript=agent_transcript[:8000])

    def call_llm(messages, temp=0.0):
        r = requests.post(
            "https://api.sarvam.ai/v1/chat/completions",
            headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"},
            json={
                "model": "sarvam-m",
                "messages": messages,
                "temperature": temp,
                "max_tokens": 800,
            },
            timeout=90,
        )
        if r.status_code != 200:
            raise RuntimeError("Sarvam LLM " + str(r.status_code) + ": " + r.text)
        return r.json()["choices"][0]["message"]["content"]

    # Attempt 1
    raw = call_llm([
        {"role": "system", "content": "Output ONLY raw JSON. No thinking. Start with { immediately."},
        {"role": "user", "content": prompt}
    ], temp=0.0)
    print("[SCORE] Attempt 1 (" + str(len(raw)) + " chars): " + raw[:60])
    js = _clean_json(raw)

    # Attempt 2 — continue conversation
    if not js or not _is_valid_json(js):
        print("[SCORE] Attempt 2...")
        raw2 = call_llm([
            {"role": "system", "content": "Output ONLY raw JSON starting with {. No thinking tags."},
            {"role": "user", "content": prompt},
            {"role": "assistant", "content": raw},
            {"role": "user", "content": "Output ONLY the JSON object now. Start with {:"}
        ], temp=0.0)
        print("[SCORE] Attempt 2 (" + str(len(raw2)) + " chars): " + raw2[:60])
        js = _clean_json(raw2)

    # Attempt 3 — minimal prompt
    if not js or not _is_valid_json(js):
        print("[SCORE] Attempt 3 minimal prompt...")
        mini = "Transcript: " + agent_transcript[:3000] + "\n\nFill scores and return ONLY this JSON:\n"
        mini += '{"scores":{"A1_opening":0,"A2_case_knowledge":0,"A3_probing":0,"A4_negotiation":0,"A5_commitment_ptp":0,"A6_closing":0,"A7_professionalism":0,"A8_call_handling":0,"A9_troubleshooting":0},"total_score":0,"total_score_pct":0,"grade":"Poor","critical_fail":false,"ptp_detected":false,"ptp_amount":null,"ptp_date":null,"ptp_mode":null,"agent_sentiment":"neutral","sentiment_notes":"note","compliance_flags":["NONE"],"summary":"summary","key_issues":["issue"],"strengths":["strength"],"coaching_tip":"tip"}'
        raw3 = call_llm([
            {"role": "system", "content": "Return ONLY the filled JSON starting with {."},
            {"role": "user", "content": mini}
        ], temp=0.0)
        print("[SCORE] Attempt 3 (" + str(len(raw3)) + " chars): " + raw3[:60])
        js = _clean_json(raw3)

    if not js or not _is_valid_json(js):
        raise ValueError("Could not extract JSON after 3 attempts. Raw: " + raw[:300])

    result = json.loads(js)
    total = result.get("total_score", 0)
    if total >= 18: result["grade"] = "Excellent"
    elif total >= 14: result["grade"] = "Good"
    elif total >= 8: result["grade"] = "Needs Improvement"
    else: result["grade"] = "Poor"

    scores = result.get("scores", {})
    critical = ["A3_probing", "A4_negotiation", "A5_commitment_ptp", "A7_professionalism"]
    result["critical_fail"] = any(scores.get(k, 1) == 0 for k in critical)

    print("[SCORE] Done " + str(total) + "/20 (" + result["grade"] + ")")
    return result


# ════════════════════════════════════
#  MAIN PIPELINE
# ════════════════════════════════════

def process_call(call_id, audio_source, calls_db, update_call_fn):
    tmp = tempfile.mkdtemp(prefix="care_dl_")
    try:
        if not os.path.isfile(audio_source):
            update_call_fn(call_id, {"status": "fetching"})
            local = resolve_audio_source(audio_source, tmp)
        else:
            local = audio_source

        update_call_fn(call_id, {"status": "transcribing"})
        print("[PIPELINE] " + call_id + " transcribing...")
        agent_transcript, full_transcript = transcribe(local)

        if not agent_transcript.strip():
            update_call_fn(call_id, {"status": "failed", "error": "Empty transcript"})
            return

        update_call_fn(call_id, {
            "transcript": full_transcript,
            "agent_transcript": agent_transcript,
            "status": "scoring"
        })
        print("[PIPELINE] " + call_id + " scoring " + str(len(agent_transcript)) + " chars...")
        s = score_transcript(agent_transcript)

        total = s.get("total_score", 0)
        pct = s.get("total_score_pct") or round((total / 20) * 100)
        flags = [f for f in s.get("compliance_flags", []) if f != "NONE"]

        update_call_fn(call_id, {
            "status": "processed",
            "score": total,
            "score_pct": pct,
            "grade": s.get("grade", "Poor"),
            "critical_fail": 1 if s.get("critical_fail") else 0,
            "scores_breakdown": s.get("scores", {}),
            "compliance_flags": flags,
            "ptp_detected": s.get("ptp_detected", False),
            "ptp_amount": s.get("ptp_amount"),
            "ptp_date": s.get("ptp_date"),
            "ptp_mode": s.get("ptp_mode"),
            "agent_sentiment": s.get("agent_sentiment", "neutral"),
            "sentiment_notes": s.get("sentiment_notes", ""),
            "summary": s.get("summary", ""),
            "key_issues": s.get("key_issues", []),
            "strengths": s.get("strengths", []),
            "coaching_tip": s.get("coaching_tip", ""),
            "processed_at": datetime.now(timezone.utc).isoformat(),
        })
        ptp = ("PTP: " + str(s.get("ptp_amount")) + " on " + str(s.get("ptp_date"))) if s.get("ptp_detected") else "No PTP"
        print("[PIPELINE] " + call_id + " DONE " + str(total) + "/20 (" + s.get("grade", "Poor") + ") | " + ptp)

    except json.JSONDecodeError as e:
        update_call_fn(call_id, {"status": "failed", "error": "Score parse error: " + str(e)})
        print("[PIPELINE] " + call_id + " JSON error: " + str(e))
    except Exception as e:
        update_call_fn(call_id, {"status": "failed", "error": str(e)})
        print("[PIPELINE] " + call_id + " ERROR: " + str(e))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def process_call_async(call_id, audio_source, calls_db, update_call_fn):
    t = threading.Thread(
        target=process_call,
        args=(call_id, audio_source, calls_db, update_call_fn),
        daemon=True
    )
    t.start()
    return t


# ════════════════════════════════════
#  CSV EXPORT
# ════════════════════════════════════

def export_calls_to_csv_bytes(calls):
    import io, csv
    output = io.StringIO()
    if not calls:
        return b""
    headers = [
        "id", "filename", "agent_id", "loan_id", "status", "score", "score_pct", "grade",
        "critical_fail", "ptp_detected", "ptp_amount", "ptp_date", "ptp_mode",
        "compliance_flags", "agent_sentiment",
        "A1_opening", "A2_case_knowledge", "A3_probing", "A4_negotiation",
        "A5_commitment_ptp", "A6_closing", "A7_professionalism",
        "A8_call_handling", "A9_troubleshooting",
        "summary", "key_issues", "strengths", "coaching_tip",
        "uploaded_at", "processed_at"
    ]
    writer = csv.DictWriter(output, fieldnames=headers, extrasaction="ignore")
    writer.writeheader()
    for c in calls:
        bd = c.get("scores_breakdown") or {}
        writer.writerow({
            "id": c.get("id", ""), "filename": c.get("filename", ""),
            "agent_id": c.get("agent_id", ""), "loan_id": c.get("loan_id", ""),
            "status": c.get("status", ""), "score": c.get("score", ""),
            "score_pct": c.get("score_pct", ""), "grade": c.get("grade", ""),
            "critical_fail": c.get("critical_fail", ""),
            "ptp_detected": c.get("ptp_detected", ""),
            "ptp_amount": c.get("ptp_amount", ""), "ptp_date": c.get("ptp_date", ""),
            "ptp_mode": c.get("ptp_mode", ""),
            "compliance_flags": "; ".join(c.get("compliance_flags") or []),
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
            "key_issues": "; ".join(c.get("key_issues") or []),
            "strengths": "; ".join(c.get("strengths") or []),
            "coaching_tip": c.get("coaching_tip", ""),
            "uploaded_at": c.get("uploaded_at", ""),
            "processed_at": c.get("processed_at", ""),
        })
    return output.getvalue().encode("utf-8")