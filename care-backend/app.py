"""
CARE Backend v4 — Flask
========================
- SQLite persistent database
- JWT auth + multi-tenant RBAC
- Google Drive sync
- CSV export
- S3 ingestion
"""

import os, uuid, io, csv, threading
from datetime import datetime, timezone, timedelta
from flask import Flask, jsonify, request, send_file
from flask_cors import CORS
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)
# Allow all origins — works for any frontend URL
CORS(app, supports_credentials=True, origins="*")

UPLOAD_FOLDER = os.path.join(os.path.dirname(__file__), "uploads")
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

ALLOWED_EXTENSIONS = {"mp3", "wav", "m4a", "ogg", "flac", "aac", "wma", "zip", "csv", "3gp", "opus", "webm"}

# ── Import DB + processor ─────────────────────────────────────────────────────
from database import (
    init_db, save_call, update_call, get_call, list_calls, purge_calls,
    get_user_by_email, get_user_by_id, create_user,
    get_drive_config, save_drive_config, update_drive_last_synced,
    get_dashboard_stats, list_loans_by_disposition, DB_TYPE,
)
from processor import (
    process_call_async,
    export_calls_to_csv_bytes,
    reprocess_call_from_existing,
    append_scoring_training_example,
    seed_scoring_examples_from_calls,
    TRAINING_EXAMPLES_PATH,
    _load_scoring_training_examples,
    parse_filename_metadata,
)
from storage import archive_local_audio, fetch_s3_audio, presigned_playback_url, persist_playback_copy, s3_configured

init_db()
REPROCESS_JOBS: dict[str, dict] = {}

# ── JWT Auth ──────────────────────────────────────────────────────────────────
SECRET = os.getenv("JWT_SECRET", "care-secret-change-in-prod")

try:
    import jwt as pyjwt
    import bcrypt
    AUTH_AVAILABLE = True
except ImportError:
    AUTH_AVAILABLE = False
    print("[AUTH] PyJWT/bcrypt not installed — auth disabled. Run: pip install pyjwt bcrypt")

def make_token(user: dict) -> str:
    if not AUTH_AVAILABLE: return "no-auth"
    payload = {
        "sub": user["id"],
        "org": user["org_id"],
        "role": user["role"],
        "name": user.get("name", ""),
        "exp": datetime.now(timezone.utc) + timedelta(hours=12)
    }
    return pyjwt.encode(payload, SECRET, algorithm="HS256")

def decode_token(token: str) -> dict | None:
    if not AUTH_AVAILABLE: return {"sub": "user_admin", "org": "org_default", "role": "super_admin"}
    try:
        return pyjwt.decode(token, SECRET, algorithms=["HS256"])
    except Exception:
        return None

def get_current_user():
    auth = request.headers.get("Authorization", "")
    token = auth.replace("Bearer ", "").strip()
    if not token:
        return None
    return decode_token(token)

def require_auth(fn):
    from functools import wraps
    @wraps(fn)
    def wrapper(*args, **kwargs):
        user = get_current_user()
        if not user:
            return jsonify({"error": "Unauthorised"}), 401
        request.user = user
        return fn(*args, **kwargs)
    return wrapper

def get_org_id():
    user = get_current_user()
    return user["org"] if user else "org_default"

def _update_call_fn(call_id, fields):
    update_call(call_id, fields)


def _public_api_base() -> str:
    base = (os.getenv("PUBLIC_API_URL") or os.getenv("RAILWAY_PUBLIC_DOMAIN") or "").strip()
    if base and not base.startswith("http"):
        base = f"https://{base}"
    if base:
        return base.rstrip("/")
    return request.host_url.rstrip("/") if request else ""


def _attach_playback_urls(call: dict) -> dict:
    """Always expose API audio URL so the player uses auth + backend proxy (no S3 CORS)."""
    if not call:
        return call
    cid = call.get("id") or ""
    path = (call.get("file_path") or "").strip()
    token = _token_from_request() if request else ""
    qs = f"?token={token}" if token else ""
    api_url = f"{_public_api_base()}/api/v1/calls/{cid}/audio{qs}" if cid else None

    available = False
    if path.startswith("s3://") and s3_configured():
        # Proxy streams via GetObject; do not require presign success for player visibility.
        available = True
    elif path.startswith(("http://", "https://")):
        available = True
    elif path and os.path.isfile(path):
        available = True
    else:
        source_uri = (call.get("source_uri") or "").strip()
        if source_uri and os.path.isfile(source_uri):
            available = True
        elif cid and _find_cached_audio(cid):
            available = True

    call["audio_playback_url"] = api_url if available else None
    call["audio_available"] = available
    return call

def allowed_file(filename):
    if not filename:
        return False
    # Accept any audio file or no extension (some recorders don't add extensions)
    if "." not in filename:
        return True  # allow extensionless files
    ext = filename.rsplit(".", 1)[1].lower()
    return ext in ALLOWED_EXTENSIONS


# ════════════════════════════════════════════════════════
#  AUTH ROUTES
# ════════════════════════════════════════════════════════

@app.route("/api/auth/login", methods=["POST"])
def login():
    body = request.get_json() or {}
    email = body.get("email", "").strip().lower()
    password = body.get("password", "")
    if not email or not password:
        return jsonify({"error": "Email and password required"}), 400

    user = get_user_by_email(email)
    if not user:
        return jsonify({"error": "Invalid credentials"}), 401

    if AUTH_AVAILABLE:
        if not bcrypt.checkpw(password.encode(), user["password_hash"].encode()):
            return jsonify({"error": "Invalid credentials"}), 401
    else:
        # Fallback: plain text compare (dev only)
        if password not in ["care@2025", user.get("password_hash", "")]:
            return jsonify({"error": "Invalid credentials"}), 401

    token = make_token(user)
    return jsonify({
        "token": token,
        "user": {"id": user["id"], "email": user["email"],
                 "name": user["name"], "role": user["role"], "org_id": user["org_id"]}
    })


@app.route("/api/auth/me", methods=["GET"])
@require_auth
def me():
    u = get_user_by_id(request.user["sub"])
    if not u: return jsonify({"error": "User not found"}), 404
    return jsonify({"id": u["id"], "email": u["email"], "name": u["name"],
                    "role": u["role"], "org_id": u["org_id"]})


@app.route("/api/v1/admin/purge-calls", methods=["POST"])
@require_auth
def admin_purge_calls():
    """
    Super admin: delete old call rows, keep newest N (default 30).
    Body: { "keep": 30, "confirm": "PURGE", "dry_run": false }
    """
    if request.user.get("role") not in ("super_admin",):
        return jsonify({"error": "Forbidden — super_admin only"}), 403
    body = request.get_json() or {}
    if str(body.get("confirm") or "").strip().upper() != "PURGE":
        return jsonify({
            "error": 'Send {"confirm":"PURGE","keep":30} to delete older calls.',
        }), 400
    keep = int(body.get("keep") or 30)
    dry_run = bool(body.get("dry_run"))
    org_id = get_org_id()
    result = purge_calls(org_id=org_id, keep=keep, dry_run=dry_run)
    REPROCESS_JOBS.clear()
    return jsonify({
        "status": "ok",
        "message": "Dry run only — no rows deleted." if dry_run else "Old calls removed from database.",
        **result,
    })


@app.route("/api/auth/register", methods=["POST"])
@require_auth
def register():
    """Super admin only — create new user."""
    if request.user.get("role") not in ["super_admin"]:
        return jsonify({"error": "Forbidden"}), 403
    body = request.get_json() or {}
    email = body.get("email", "").strip().lower()
    password = body.get("password", "")
    role = body.get("role", "qa_manager")
    name = body.get("name", "")
    if not email or not password:
        return jsonify({"error": "email and password required"}), 400
    pw_hash = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode() if AUTH_AVAILABLE else password
    uid = f"user_{uuid.uuid4().hex[:8]}"
    create_user(uid, request.user["org"], email, pw_hash, role, name)
    return jsonify({"id": uid, "email": email, "role": role}), 201


# ════════════════════════════════════════════════════════
#  HEALTH
# ════════════════════════════════════════════════════════

@app.route("/api/health")
def health():
    try:
        list_calls(limit=1)
        db_ok = True
    except Exception as exc:
        db_ok = False
        print(f"[HEALTH] DB check failed: {exc}", flush=True)
    try:
        from processor import _ffmpeg_bin
        ffmpeg_path = _ffmpeg_bin()
    except Exception:
        ffmpeg_path = None
    build_id = "unknown"
    try:
        build_path = os.path.join(os.path.dirname(__file__), "BUILD_ID.txt")
        if os.path.isfile(build_path):
            build_id = open(build_path, encoding="utf-8").read().strip()
    except Exception:
        pass
    return jsonify({
        "status": "ok" if db_ok else "degraded",
        "db": DB_TYPE,
        "db_ok": db_ok,
        "sarvam": bool(os.getenv("SARVAM_API_KEY")),
        "ffmpeg": ffmpeg_path or False,
        "build": build_id,
        "s3_configured": s3_configured(),
    })


# ════════════════════════════════════════════════════════
#  CALL INGESTION
# ════════════════════════════════════════════════════════

@app.route("/api/v1/calls/ingest", methods=["GET", "POST"])
def ingest_call():
    if request.method == "GET":
        return jsonify({
            "endpoint": "/api/v1/calls/ingest",
            "method": "POST",
            "content_type": "multipart/form-data",
            "fields": {
                "file": "required — audio file (.mp3, .wav, …)",
                "agent_id": "optional",
                "loan_id": "optional",
                "campaign_id": "optional",
            },
            "status": "ready",
            "hint": "Opening this URL in a browser uses GET; uploads must use POST from the CARE dashboard or curl.",
        })

    if "file" not in request.files:
        return jsonify({"error": "No file provided"}), 400
    file = request.files["file"]

    # Accept all files — be permissive for demo
    filename = file.filename or "recording.mp3"

    call_id = f"CALL-{uuid.uuid4().hex[:8].upper()}"
    # Sanitize filename
    safe_name = "".join(c if c.isalnum() or c in "._- " else "_" for c in filename)
    save_path = os.path.join(UPLOAD_FOLDER, f"{call_id}_{safe_name}")

    try:
        file.save(save_path)
    except Exception as e:
        return jsonify({"error": f"Failed to save file: {str(e)}"}), 500

    if not os.path.exists(save_path) or os.path.getsize(save_path) == 0:
        return jsonify({"error": "File save failed — empty file"}), 500

    file_size = os.path.getsize(save_path)
    org_id = get_org_id()

    record = {
        "id": call_id, "org_id": org_id,
        "filename": file.filename, "file_path": save_path, "file_size": file_size,
        "source": "upload", "status": "queued",
        "uploaded_at": datetime.now(timezone.utc).isoformat(),
    }
    for field in ("agent_id", "campaign_id", "loan_id"):
        val = (request.form.get(field) or "").strip()
        if val:
            record[field] = val

    try:
        s3_uri = archive_local_audio(save_path, call_id, safe_name)
        if s3_uri:
            record["file_path"] = s3_uri
            record["source_uri"] = save_path
        save_call(record)
        process_call_async(call_id, save_path, {}, lambda cid, fields: update_call(cid, fields))
    except Exception as e:
        print(f"[UPLOAD] {call_id} failed: {e}", flush=True)
        if os.path.exists(save_path):
            try:
                os.remove(save_path)
            except OSError:
                pass
        return jsonify({"error": "Failed to queue call", "detail": str(e)}), 500

    print(f"[UPLOAD] {file.filename} → {call_id} ({file_size} bytes)")
    return jsonify({"call_id": call_id, "status": "queued"}), 201


@app.route("/api/v1/calls/ingest-s3", methods=["POST"])
def ingest_from_s3():
    body = request.get_json() or {}
    s3_uri = body.get("s3_uri", "")
    if not s3_uri.startswith("s3://"):
        return jsonify({"error": "s3_uri required (format: s3://bucket/key)"}), 400
    call_id = f"CALL-{uuid.uuid4().hex[:8].upper()}"
    org_id = get_org_id()
    record = {
        "id": call_id, "org_id": org_id,
        "filename": s3_uri.split("/")[-1], "file_path": s3_uri,
        "agent_id": body.get("agent_id"), "loan_id": body.get("loan_id"),
        "source": "s3", "source_uri": s3_uri, "status": "queued",
        "uploaded_at": datetime.now(timezone.utc).isoformat(),
    }
    try:
        save_call(record)
        process_call_async(call_id, s3_uri, {}, lambda cid, f: update_call(cid, f))
    except Exception as e:
        print(f"[S3-INGEST] {call_id} failed: {e}", flush=True)
        return jsonify({"error": "Failed to queue call", "detail": str(e)}), 500
    return jsonify({"call_id": call_id, "status": "queued", "source": "s3"}), 201


@app.route("/api/v1/calls/ingest-url", methods=["POST"])
def ingest_from_url():
    body = request.get_json() or {}
    url = body.get("url", "")
    if not url.startswith("http"):
        return jsonify({"error": "url required"}), 400
    call_id = f"CALL-{uuid.uuid4().hex[:8].upper()}"
    org_id = get_org_id()
    filename = body.get("filename") or url.split("/")[-1].split("?")[0] or "audio.mp3"
    record = {
        "id": call_id, "org_id": org_id,
        "filename": filename, "file_path": url,
        "agent_id": body.get("agent_id"), "loan_id": body.get("loan_id"),
        "source": "url", "source_uri": url, "status": "queued",
        "uploaded_at": datetime.now(timezone.utc).isoformat(),
    }
    try:
        save_call(record)
        process_call_async(call_id, url, {}, lambda cid, f: update_call(cid, f))
    except Exception as e:
        print(f"[URL-INGEST] {call_id} failed: {e}", flush=True)
        return jsonify({"error": "Failed to queue call", "detail": str(e)}), 500
    return jsonify({"call_id": call_id, "status": "queued"}), 201


# ════════════════════════════════════════════════════════
#  GOOGLE DRIVE SYNC
# ════════════════════════════════════════════════════════

@app.route("/api/v1/connectors/gdrive/config", methods=["POST"])
@require_auth
def save_gdrive_config():
    body = request.get_json() or {}
    folder_url = body.get("folder_url", "")
    auto_sync = body.get("auto_sync", False)
    # Extract folder ID from URL
    folder_id = ""
    if "/folders/" in folder_url:
        folder_id = folder_url.split("/folders/")[1].split("?")[0].split("/")[0]
    elif "id=" in folder_url:
        folder_id = folder_url.split("id=")[1].split("&")[0]
    else:
        folder_id = folder_url  # assume raw ID
    save_drive_config(request.user["org"], folder_url, folder_id, auto_sync)
    return jsonify({"folder_id": folder_id, "auto_sync": auto_sync})


@app.route("/api/v1/connectors/gdrive/sync", methods=["GET", "POST"])
@require_auth
def sync_gdrive():
    """
    Pull audio files from a configured Google Drive folder.
    Lists all .mp3/.wav/.m4a files and queues each for processing.
    Uses direct download URL (files must be shared 'Anyone with link').
    """
    import requests as req

    org_id = request.user["org"]
    cfg = get_drive_config(org_id)

    # Allow passing folder_id directly in request
    body = request.get_json() or {}
    folder_id = body.get("folder_id") or (cfg["folder_id"] if cfg else None)

    if not folder_id:
        return jsonify({"error": "No Google Drive folder configured. POST to /api/v1/connectors/gdrive/config first."}), 400

    # Use Google Drive API public endpoint (no OAuth needed for shared folders)
    api_url = (
        f"https://www.googleapis.com/drive/v3/files"
        f"?q='{folder_id}'+in+parents+and+(mimeType='audio/mpeg'+or+mimeType='audio/wav'+or+mimeType='audio/x-m4a')"
        f"&fields=files(id,name,size,mimeType,modifiedTime)"
        f"&key={os.getenv('GOOGLE_API_KEY','')}"
    )

    # If no API key, fall back to direct URL processing
    if not os.getenv("GOOGLE_API_KEY"):
        return jsonify({
            "message": "To auto-list Drive files, set GOOGLE_API_KEY in .env. Alternatively, use /api/v1/calls/ingest-url with individual Drive file links.",
            "manual_url_endpoint": "POST /api/v1/calls/ingest-url",
            "example": {"url": f"https://drive.google.com/uc?export=download&id=FILE_ID&confirm=t"}
        }), 200

    r = req.get(api_url, timeout=30)
    if r.status_code != 200:
        return jsonify({"error": f"Drive API error: {r.text[:200]}"}), 400

    files = r.json().get("files", [])
    queued = []

    for f in files:
        dl_url = f"https://drive.google.com/uc?export=download&id={f['id']}&confirm=t"
        call_id = f"CALL-{uuid.uuid4().hex[:8].upper()}"
        meta = parse_filename_metadata(f.get("name") or "")
        record = {
            "id": call_id, "org_id": org_id,
            "filename": f["name"], "file_path": dl_url,
            "source": "gdrive", "source_uri": dl_url,
            "status": "queued",
            "agent_id": meta.get("agent_id") if meta.get("agent_id") != "Unknown" else None,
            "loan_id": meta.get("loan_id") if meta.get("loan_id") != "Unknown" else None,
            "uploaded_at": datetime.now(timezone.utc).isoformat(),
        }
        save_call(record)
        process_call_async(call_id, dl_url, record, lambda cid, flds: update_call(cid, flds))
        queued.append({"call_id": call_id, "filename": f["name"]})

    update_drive_last_synced(org_id)
    return jsonify({"synced": len(queued), "calls": queued})


# ════════════════════════════════════════════════════════
#  CALL QUERIES
# ════════════════════════════════════════════════════════

@app.route("/api/v1/calls", methods=["GET"])
def list_calls_route():
    org_id = get_org_id()
    try:
        limit = min(int(request.args.get("limit", 50)), 500)
    except ValueError:
        limit = 50
    calls = list_calls(
        org_id=org_id,
        date_from=request.args.get("from"),
        date_to=request.args.get("to"),
        agent_id=request.args.get("agent_id"),
        status=request.args.get("status"),
        disposition=request.args.get("disposition"),
        limit=limit,
    )
    return jsonify({"calls": calls, "total": len(calls)})


def _guess_audio_mime(filename: str) -> str:
    ext = (filename or "").rsplit(".", 1)[-1].lower() if filename and "." in filename else "mpeg"
    return {
        "mp3": "audio/mpeg", "wav": "audio/wav", "m4a": "audio/mp4",
        "ogg": "audio/ogg", "flac": "audio/flac", "aac": "audio/aac", "webm": "audio/webm",
    }.get(ext, "audio/mpeg")


def _token_from_request() -> str:
    auth = request.headers.get("Authorization", "")
    token = auth.replace("Bearer ", "").strip()
    return token or (request.args.get("token") or "").strip()


@app.route("/api/v1/calls/<call_id>", methods=["GET"])
def get_call_route(call_id):
    call = get_call(call_id)
    if not call:
        return jsonify({"error": "Not found"}), 404
    call = _attach_playback_urls(call)
    return jsonify(call)


def _run_reprocess_job(job_id: str, selected_calls: list[dict]):
    job = REPROCESS_JOBS.get(job_id, {})
    job["status"] = "running"
    ok_count = 0
    fail_count = 0
    done_ids: list[str] = []
    failed: list[dict] = []

    for call in selected_calls:
        cid = call.get("id")
        if not cid:
            continue
        passed = reprocess_call_from_existing(cid, call, _update_call_fn)
        done_ids.append(cid)
        if passed:
            ok_count += 1
        else:
            fail_count += 1
            failed.append({"id": cid, "error": "Reprocess failed. Check backend logs."})
        job["processed"] = len(done_ids)
        job["success"] = ok_count
        job["failed"] = fail_count

    job["status"] = "completed"
    job["completed_at"] = datetime.now(timezone.utc).isoformat()
    job["done_ids"] = done_ids
    job["failed_items"] = failed
    REPROCESS_JOBS[job_id] = job


@app.route("/api/v1/calls/<call_id>/reprocess", methods=["POST"])
def reprocess_single_call(call_id):
    org_id = get_org_id()
    call = get_call(call_id, org_id=org_id) or get_call(call_id)
    if not call:
        return jsonify({"error": "Call not found"}), 404
    ok = reprocess_call_from_existing(call_id, call, _update_call_fn)
    updated = get_call(call_id, org_id=org_id) or get_call(call_id)
    if not ok:
        return jsonify({"error": "Reprocess failed", "call": updated}), 500
    return jsonify({"status": "ok", "message": "Call reprocessed", "call": _attach_playback_urls(updated)})


@app.route("/api/v1/calls/reprocess", methods=["POST"])
def reprocess_calls_bulk():
    """
    Bulk reprocess already-processed calls using stored transcript + filename metadata.
    Body:
      {
        "call_ids": ["CALL-..."],   // optional
        "limit": 500,               // optional
        "status": "processed"       // optional (default processed)
      }
    """
    body = request.get_json() or {}
    org_id = get_org_id()
    limit = int(body.get("limit") or 500)
    limit = max(1, min(limit, 5000))
    status = (body.get("status") or "processed").strip()
    requested_ids = [str(x).strip() for x in (body.get("call_ids") or []) if str(x).strip()]

    rows = list_calls(
        org_id=org_id,
        date_from=body.get("from"),
        date_to=body.get("to"),
        agent_id=body.get("agent_id"),
        disposition=body.get("disposition"),
        limit=limit,
    )
    if status:
        rows = [c for c in rows if str(c.get("status") or "").lower() == status.lower()]
    if requested_ids:
        wanted = set(requested_ids)
        rows = [c for c in rows if c.get("id") in wanted]

    rows = [c for c in rows if str(c.get("transcript") or "").strip()]
    if not rows:
        return jsonify({"error": "No eligible calls found for reprocess"}), 404

    job_id = f"REPROC-{uuid.uuid4().hex[:10].upper()}"
    REPROCESS_JOBS[job_id] = {
        "id": job_id,
        "status": "queued",
        "org_id": org_id,
        "total": len(rows),
        "processed": 0,
        "success": 0,
        "failed": 0,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "sample_ids": [r.get("id") for r in rows[:10]],
    }
    threading.Thread(target=_run_reprocess_job, args=(job_id, rows), daemon=True).start()
    return jsonify({"job_id": job_id, "status": "queued", "total": len(rows)}), 202


@app.route("/api/v1/calls/reprocess/<job_id>", methods=["GET"])
def reprocess_job_status(job_id):
    job = REPROCESS_JOBS.get(job_id)
    if not job:
        return jsonify({"error": "Job not found"}), 404
    return jsonify(job)


@app.route("/api/v1/training/scoring/add-example", methods=["POST"])
def add_scoring_training_example_route():
    """
    Add a reviewed call as a few-shot training example for scorer calibration.
    Body:
      {
        "call_id": "CALL-XXXX",
        "tags": ["third_party_safe", "rpc"],
        "override": { ...optional expected json override... }
      }
    """
    body = request.get_json() or {}
    call_id = (body.get("call_id") or "").strip()
    if not call_id:
        return jsonify({"error": "call_id is required"}), 400

    call = get_call(call_id, org_id=get_org_id()) or get_call(call_id)
    if not call:
        return jsonify({"error": "call not found"}), 404
    transcript = str(call.get("transcript") or "").strip()
    if not transcript:
        return jsonify({"error": "call has no transcript"}), 400

    expected = body.get("override") or {
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
    append_scoring_training_example({
        "id": call_id,
        "tags": body.get("tags") or [],
        "transcript": transcript,
        "expected_json": expected,
    })
    return jsonify({"status": "ok", "message": "Training example added", "call_id": call_id})


@app.route("/api/v1/training/scoring/examples", methods=["GET"])
def list_scoring_training_examples():
    """List few-shot example count and ids (not full transcripts)."""
    examples = _load_scoring_training_examples()
    return jsonify({
        "path": TRAINING_EXAMPLES_PATH,
        "count": len(examples),
        "examples": [
            {"id": ex.get("id"), "tags": ex.get("tags") or [], "transcript_chars": len(ex.get("transcript") or "")}
            for ex in examples
        ],
    })


@app.route("/api/v1/training/scoring/seed-from-calls", methods=["POST"])
def seed_scoring_training_examples_route():
    """
    Seed few-shot file from best processed calls in DB (super_admin).
    Body: { "min_score_pct": 70, "max_examples": 12, "merge": true }
    """
    if request.user.get("role") not in ("super_admin",):
        return jsonify({"error": "Forbidden — super_admin only"}), 403
    body = request.get_json() or {}
    calls = list_calls(org_id=get_org_id(), status="processed", limit=500)
    result = seed_scoring_examples_from_calls(
        calls,
        min_score_pct=int(body.get("min_score_pct") or 70),
        max_examples=int(body.get("max_examples") or 12),
        merge=body.get("merge", True) is not False,
    )
    return jsonify({"status": "ok", **result})


def _find_cached_audio(call_id: str) -> str | None:
    if not call_id or not os.path.isdir(UPLOAD_FOLDER):
        return None
    for name in os.listdir(UPLOAD_FOLDER):
        if name.startswith(call_id) and os.path.isfile(os.path.join(UPLOAD_FOLDER, name)):
            return os.path.join(UPLOAD_FOLDER, name)
    return None


@app.route("/api/v1/calls/<call_id>/audio", methods=["GET"])
def get_call_audio(call_id):
    """Stream recording via backend proxy (local, S3, or cached Drive/URL)."""
    user = decode_token(_token_from_request())
    # Match GET /calls/<id>: do not 401 when JWT expired — detail page already shows the call.
    call = get_call(call_id, org_id=user["org"] if user else None)
    if not call:
        call = get_call(call_id)
    if not call:
        return jsonify({"error": "Not found"}), 404

    path = (call.get("file_path") or "").strip()
    filename = call.get("filename") or "recording.mp3"

    if path.startswith("s3://"):
        fetched = fetch_s3_audio(path)
        if fetched:
            data, mime = fetched
            if data:
                from io import BytesIO
                return send_file(
                    BytesIO(data),
                    mimetype=mime,
                    download_name=filename,
                    conditional=True,
                    max_age=3600,
                )
        return jsonify({
            "error": "S3 audio unavailable",
            "hint": "Check AWS credentials, bucket region, and s3:GetObject on file_path",
            "file_path": path,
            "s3_configured": s3_configured(),
        }), 502

    if path.startswith(("http://", "https://")):
        cached = _find_cached_audio(call_id)
        if cached:
            return send_file(
                cached,
                mimetype=_guess_audio_mime(filename),
                download_name=filename,
                conditional=True,
                max_age=3600,
            )
        import tempfile
        import shutil
        from processor import resolve_audio_source

        tmp = tempfile.mkdtemp(prefix="care_play_")
        try:
            local = resolve_audio_source(path, tmp)
            dest = os.path.join(UPLOAD_FOLDER, f"{call_id}_{os.path.basename(local)}")
            shutil.copy2(local, dest)
            s3_uri = archive_local_audio(dest, call_id, os.path.basename(dest))
            if s3_uri:
                update_call(call_id, {"file_path": s3_uri})
                fetched = fetch_s3_audio(s3_uri)
                if fetched:
                    data, mime = fetched
                    from io import BytesIO
                    return send_file(
                        BytesIO(data),
                        mimetype=mime,
                        download_name=filename,
                        conditional=True,
                        max_age=3600,
                    )
            else:
                update_call(call_id, {"file_path": dest})
            return send_file(
                dest,
                mimetype=_guess_audio_mime(filename),
                download_name=filename,
                conditional=True,
                max_age=3600,
            )
        except Exception as exc:
            return jsonify({"error": f"Could not fetch audio: {exc}"}), 502
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    local_fallback = (call.get("source_uri") or "").strip()
    if local_fallback and os.path.isfile(local_fallback):
        path = local_fallback
        filename = os.path.basename(local_fallback)

    if os.path.isfile(path):
        return send_file(
            path,
            mimetype=_guess_audio_mime(filename),
            download_name=filename,
            conditional=True,
            max_age=3600,
        )

    cached = _find_cached_audio(call_id)
    if cached:
        return send_file(
            cached,
            mimetype=_guess_audio_mime(filename),
            download_name=filename,
            conditional=True,
            max_age=3600,
        )

    return jsonify({
        "error": "Audio file not found on server",
        "hint": "Enable S3 archive: set AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY, S3_AUDIO_BUCKET on Railway",
        "s3_configured": s3_configured(),
    }), 404


# ════════════════════════════════════════════════════════
#  REPORTS & EXPORTS
# ════════════════════════════════════════════════════════

@app.route("/api/v1/reports/dashboard", methods=["GET"])
def dashboard():
    org_id = get_org_id()
    try:
        date_from = request.args.get("from")
        date_to = request.args.get("to")
        agent_id = request.args.get("agent_id")
        disposition = request.args.get("disposition")
        stats = get_dashboard_stats(
            org_id=org_id,
            date_from=date_from,
            date_to=date_to,
            agent_id=agent_id,
            disposition=disposition,
        )
        return jsonify(stats)
    except Exception as exc:
        print(f"[DASHBOARD] Failed for org={org_id}: {exc}", flush=True)
        return jsonify({"error": "Dashboard aggregation failed", "detail": str(exc)}), 500


@app.route("/api/v1/reports/disposition-loans", methods=["GET"])
def disposition_loans():
    """Download loan IDs for a disposition category (portfolio-level export)."""
    org_id = get_org_id()
    disposition = (request.args.get("disposition") or "").strip()
    if not disposition:
        return jsonify({"error": "disposition query param required"}), 400

    rows = list_loans_by_disposition(
        org_id=org_id,
        disposition=disposition,
        date_from=request.args.get("from"),
        date_to=request.args.get("to"),
    )

    if request.args.get("format") == "json":
        return jsonify({
            "disposition": disposition,
            "count": len(rows),
            "loans": rows,
        })

    import csv
    buf = io.StringIO()
    fieldnames = [
        "loan_id", "call_id", "agent_id", "filename", "disposition",
        "score_pct", "risk_level", "ai_detection", "ai_suggestion", "uploaded_at",
    ]
    writer = csv.DictWriter(buf, fieldnames=fieldnames, extrasaction="ignore")
    writer.writeheader()
    for row in rows:
        writer.writerow(row)
    safe_name = disposition.lower().replace(" ", "_")
    return send_file(
        io.BytesIO(buf.getvalue().encode("utf-8-sig")),
        mimetype="text/csv",
        as_attachment=True,
        download_name=f"CARE_{safe_name}_loan_ids.csv",
    )


@app.route("/api/v1/reports/export", methods=["GET"])
def export_csv():
    """Download all processed calls as CSV."""
    org_id = get_org_id()
    calls = list_calls(
        org_id=org_id,
        date_from=request.args.get("from"),
        date_to=request.args.get("to"),
        limit=10000
    )
    processed = [c for c in calls if c["status"] == "processed"]
    csv_bytes = export_calls_to_csv_bytes(processed)
    date_str = datetime.now().strftime("%Y%m%d")
    return send_file(
        io.BytesIO(csv_bytes),
        mimetype="text/csv",
        as_attachment=True,
        download_name=f"CARE_Export_{date_str}.csv"
    )


@app.route("/api/v1/agents/kpis", methods=["GET"])
def agent_kpis():
    org_id = get_org_id()
    processed = [c for c in list_calls(org_id=org_id, limit=1000) if c["status"] == "processed"]
    agents = {}
    for c in processed:
        aid = c.get("agent_id") or "Unknown"
        if aid not in agents:
            agents[aid] = {"agent_id": aid, "calls": 0, "total_score": 0, "ptps": 0, "flags": 0}
        agents[aid]["calls"] += 1
        agents[aid]["total_score"] += c.get("score") or 0
        if c.get("ptp_detected"): agents[aid]["ptps"] += 1
        agents[aid]["flags"] += len(c.get("compliance_flags") or [])
    result = []
    for a in agents.values():
        a["avg_score"] = round(a["total_score"]/a["calls"], 1) if a["calls"] else 0
        a["ptp_rate"] = round(a["ptps"]/a["calls"]*100) if a["calls"] else 0
        result.append(a)
    return jsonify({"agents": sorted(result, key=lambda x: x["avg_score"], reverse=True)})


# ════════════════════════════════════════════════════════
if __name__ == "__main__":
    print("🎯 CARE Backend v4")
    print(f"   DB      : {os.path.join(os.path.dirname(__file__), 'care.db')}")
    print(f"   Sarvam  : {'✓ set' if os.getenv('SARVAM_API_KEY') else '✗ MISSING'}")
    print(f"   Auth    : {'JWT enabled' if AUTH_AVAILABLE else 'disabled (pip install pyjwt bcrypt)'}")
    print(f"   Health  : http://localhost:5000/api/health\n")
    app.run(debug=True, port=5000, threaded=True)


# ════════════════════════════════════════════════════════
# Entry point
# ════════════════════════════════════════════════════════
if __name__ == "__main__":
    _port = os.getenv("PORT", "5000")
    port = int(_port) if str(_port).isdigit() else 5000
    debug = os.getenv("FLASK_ENV", "production") == "development"
    print("🎯 CARE Backend v4")
    print(f"   Port    : {port}")
    print(f"   Sarvam  : {'✓ set' if os.getenv('SARVAM_API_KEY') else '✗ MISSING'}")
    app.run(debug=debug, port=port, threaded=True)