"""S3 audio archive + presigned playback URLs for Railway (ephemeral local disk)."""

from __future__ import annotations

import os
import re
import shutil


def s3_configured() -> bool:
    return bool(os.getenv("AWS_ACCESS_KEY_ID") and os.getenv("AWS_SECRET_ACCESS_KEY"))


def _s3_client():
    import boto3
    return boto3.client(
        "s3",
        region_name=os.getenv("AWS_REGION", "eu-north-1"),
        aws_access_key_id=os.getenv("AWS_ACCESS_KEY_ID"),
        aws_secret_access_key=os.getenv("AWS_SECRET_ACCESS_KEY"),
    )


def default_bucket() -> str:
    return (
        os.getenv("S3_AUDIO_BUCKET")
        or os.getenv("S3_BUCKET")
        or "verbilab-care-audio-2026"
    )


def archive_local_audio(local_path: str, call_id: str, filename: str) -> str | None:
    """Upload local recording to S3; return s3:// URI or None if skipped."""
    if not s3_configured() or not local_path or not os.path.isfile(local_path):
        return None
    safe = re.sub(r"[^\w.\-]+", "_", filename or "recording.mp3")
    key = f"calls/{call_id}/{safe}"
    bucket = default_bucket()
    try:
        client = _s3_client()
        ext = safe.rsplit(".", 1)[-1].lower() if "." in safe else "mpeg"
        content_type = {
            "mp3": "audio/mpeg", "wav": "audio/wav", "m4a": "audio/mp4",
            "ogg": "audio/ogg", "flac": "audio/flac", "aac": "audio/aac",
        }.get(ext, "audio/mpeg")
        client.upload_file(
            local_path,
            bucket,
            key,
            ExtraArgs={"ContentType": content_type},
        )
        uri = f"s3://{bucket}/{key}"
        print(f"[S3] Archived playback {uri}", flush=True)
        return uri
    except Exception as exc:
        print(f"[S3] Archive failed (playback may be unavailable): {exc}", flush=True)
        return None


def persist_playback_copy(local_path: str, call_id: str, filename: str, upload_dir: str) -> str | None:
    """Copy processed audio into uploads/ so /audio can stream it if S3 is unavailable."""
    if not local_path or not os.path.isfile(local_path):
        return None
    os.makedirs(upload_dir, exist_ok=True)
    safe = re.sub(r"[^\w.\-]+", "_", filename or "recording.mp3")
    dest = os.path.join(upload_dir, f"{call_id}_{safe}")
    try:
        shutil.copy2(local_path, dest)
        print(f"[PLAYBACK] Cached local copy {dest}", flush=True)
        return dest
    except Exception as exc:
        print(f"[PLAYBACK] Local cache failed: {exc}", flush=True)
        return None


def presigned_playback_url(s3_uri: str, expires: int = 3600) -> str | None:
    if not s3_uri or not s3_uri.startswith("s3://") or not s3_configured():
        return None
    uri = s3_uri.replace("s3://", "", 1)
    bucket, _, key = uri.partition("/")
    if not bucket or not key:
        return None
    try:
        return _s3_client().generate_presigned_url(
            "get_object",
            Params={"Bucket": bucket, "Key": key},
            ExpiresIn=expires,
        )
    except Exception as exc:
        print(f"[S3] Presign failed: {exc}", flush=True)
        return None
