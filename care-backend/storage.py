"""S3 audio archive + presigned playback URLs (EC2 / ECS — local uploads/ cache for playback)."""

from __future__ import annotations

import os
import re
import shutil


def _candidate_s3_keys(key: str) -> list[str]:
    """Try common legacy prefixes when stored S3 key is stale/misaligned."""
    key = (key or "").lstrip("/")
    if not key:
        return []
    options = [key]
    basename = key.rsplit("/", 1)[-1] if "/" in key else key
    if key.startswith("calls/"):
        options.append("audio/" + key.split("/", 1)[1])
    elif key.startswith("audio/"):
        options.append("calls/" + key.split("/", 1)[1])
    if basename and basename != key:
        options.extend([f"audio/{basename}", f"calls/{basename}"])
    return list(dict.fromkeys(options))


def s3_configured() -> bool:
    return bool(os.getenv("AWS_ACCESS_KEY_ID") and os.getenv("AWS_SECRET_ACCESS_KEY"))


_BUCKET_REGION_CACHE: dict[str, str] = {}


def resolve_bucket_region(bucket: str) -> str:
    """
    Return the AWS region where the S3 bucket actually lives.
    Do NOT use ECS/Railway AWS_REGION (e.g. us-east-1) for eu-north-1 buckets — that causes 403.
    """
    bucket = (bucket or default_bucket()).strip()
    if bucket in _BUCKET_REGION_CACHE:
        return _BUCKET_REGION_CACHE[bucket]

    audio_region = (os.getenv("S3_AUDIO_REGION") or "").strip()
    if audio_region:
        _BUCKET_REGION_CACHE[bucket] = audio_region
        return audio_region

    import boto3
    try:
        probe = boto3.client(
            "s3",
            region_name="us-east-1",
            aws_access_key_id=os.getenv("AWS_ACCESS_KEY_ID"),
            aws_secret_access_key=os.getenv("AWS_SECRET_ACCESS_KEY"),
        )
        loc = probe.get_bucket_location(Bucket=bucket).get("LocationConstraint")
        region = loc or "us-east-1"
        _BUCKET_REGION_CACHE[bucket] = region
        print(f"[S3] Auto-detected bucket region for {bucket}: {region}", flush=True)
        return region
    except Exception as exc:
        print(f"[S3] Bucket region detect failed for {bucket}: {exc}", flush=True)
        fallback = "eu-north-1" if "verbilab-care" in bucket else (
            os.getenv("AWS_REGION") or os.getenv("AWS_DEFAULT_REGION") or "eu-north-1"
        )
        _BUCKET_REGION_CACHE[bucket] = fallback
        return fallback


def _s3_client(bucket: str | None = None):
    if not s3_configured():
        raise RuntimeError(
            "AWS S3 credentials not configured. Set AWS_ACCESS_KEY_ID and "
            "AWS_SECRET_ACCESS_KEY in .env (IAM user needs s3:GetObject + s3:PutObject on the bucket)."
        )
    import boto3
    region = resolve_bucket_region(bucket or default_bucket())
    return boto3.client(
        "s3",
        region_name=region,
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


def parse_s3_uri(s3_uri: str) -> tuple[str, str] | None:
    if not s3_uri or not s3_uri.startswith("s3://"):
        return None
    uri = s3_uri.replace("s3://", "", 1).strip()
    bucket, _, key = uri.partition("/")
    if not bucket or not key:
        return None
    return bucket, key


def fetch_s3_audio(s3_uri: str) -> tuple[bytes, str] | None:
    """Download object bytes for proxy streaming (avoids browser CORS on presigned URLs)."""
    parsed = parse_s3_uri(s3_uri)
    if not parsed or not s3_configured():
        return None
    bucket, key = parsed
    region = resolve_bucket_region(bucket)
    try:
        from botocore.exceptions import ClientError
    except ImportError:
        ClientError = Exception  # type: ignore

    last_err = None
    client = _s3_client(bucket)
    for candidate in _candidate_s3_keys(key):
        try:
            obj = client.get_object(Bucket=bucket, Key=candidate)
            body = obj["Body"].read()
            ext = candidate.rsplit(".", 1)[-1].lower() if "." in candidate else "mpeg"
            mime = {
                "mp3": "audio/mpeg", "wav": "audio/wav", "m4a": "audio/mp4",
                "ogg": "audio/ogg", "flac": "audio/flac", "aac": "audio/aac",
            }.get(ext, obj.get("ContentType") or "audio/mpeg")
            if candidate != key:
                print(f"[S3] fetch fallback key used: {candidate}", flush=True)
            return body, mime
        except ClientError as exc:
            last_err = exc
            continue
        except Exception as exc:
            last_err = exc
            continue

    code = getattr(last_err, "response", {}).get("Error", {}).get("Code") if last_err else ""
    if code in {"403", "AccessDenied"}:
        print(
            f"[S3] 403 for {s3_uri} (bucket region={region}). "
            "Usually IAM s3:GetObject on arn:aws:s3:::verbilab-care-audio-2026/* — "
            "not because ECS/Railway is in a different region.",
            flush=True,
        )
    else:
        print(f"[S3] fetch failed for {s3_uri}: {last_err}", flush=True)
    return None


def presigned_playback_url(s3_uri: str, expires: int = 3600) -> str | None:
    if not s3_uri or not s3_uri.startswith("s3://") or not s3_configured():
        return None
    uri = s3_uri.replace("s3://", "", 1)
    bucket, _, key = uri.partition("/")
    if not bucket or not key:
        return None
    try:
        return _s3_client(bucket).generate_presigned_url(
            "get_object",
            Params={"Bucket": bucket, "Key": key},
            ExpiresIn=expires,
        )
    except Exception as exc:
        print(f"[S3] Presign failed: {exc}", flush=True)
        return None
