"""Extract agent names and loan IDs from call filenames."""

from __future__ import annotations

import os
import re
from urllib.parse import unquote

BAD_AGENT_TOKENS = {
    "audio", "sample", "samples", "samplecare", "gdrive", "mp", "_mp", "mp3", "wav", "m4a",
    "undefined", "null", "unknown", "call", "calls", "resources", "file", "recording",
    "verbilab", "care", "upload", "download", "test", "demo", "no", "name",
}


def is_bad_agent_token(token: str) -> bool:
    t = str(token or "").strip().lower()
    if not t or len(t) < 3:
        return True
    if t in BAD_AGENT_TOKENS:
        return True
    if re.fullmatch(r"call-[a-f0-9]+", t, re.I):
        return True
    if re.fullmatch(r"\d+", t):
        return True
    return False


def looks_like_random_id(token: str) -> bool:
    t = str(token or "").strip()
    if len(t) < 6:
        return False
    has_lower = bool(re.search(r"[a-z]", t))
    has_upper = bool(re.search(r"[A-Z]", t))
    has_digit = bool(re.search(r"\d", t))
    if has_lower and has_upper and (has_digit or len(t) >= 8):
        return True
    if re.fullmatch(r"[A-F0-9]{8,}", t, re.I) and has_digit:
        return True
    if re.fullmatch(r"[A-Za-z0-9]{8,}", t) and not re.search(r"[aeiouAEIOU]", t):
        return True
    return False


def extract_agent_name(token: str) -> str:
    """Pull a human agent name from tokens like sidd009334, 23330sidd, or RITIKA."""
    t = str(token or "").strip()
    if not t or is_bad_agent_token(t) or looks_like_random_id(t):
        return ""

    if re.fullmatch(r"[A-Za-z]{3,20}", t):
        return t

    m = re.match(r"^([A-Za-z]{3,20})(\d+)$", t)
    if m and not is_bad_agent_token(m.group(1)):
        return m.group(1)

    m = re.match(r"^(\d{4,})([A-Za-z]{3,20})$", t)
    if m and not is_bad_agent_token(m.group(2)):
        return m.group(2)

    runs = re.findall(r"[A-Za-z]{3,20}", t)
    for run in sorted(runs, key=len, reverse=True):
        if not is_bad_agent_token(run) and not looks_like_random_id(run):
            return run
    return ""


def _clean_stem(filename: str) -> str:
    raw = str(filename or "").strip()
    if not raw:
        return ""
    base = os.path.basename(unquote(raw.split("?", 1)[0]))
    stem = os.path.splitext(base)[0].strip()
    return re.sub(r"^CALL-[A-F0-9]{6,12}_", "", stem, flags=re.I)


def parse_agent_loan_from_filename(filename: str) -> dict[str, str]:
    """Return {agent_id, loan_id} with clean agent name when detectable."""
    cleaned = _clean_stem(filename)
    if not cleaned:
        return {"agent_id": "", "loan_id": ""}

    if re.fullmatch(r"gdrive_[a-zA-Z0-9_-]+", cleaned, re.I):
        return {"agent_id": "", "loan_id": ""}

    # AgentName_LoanNumber
    m = re.match(r"^([A-Za-z][A-Za-z0-9.-]{1,})_(\d{4,}[A-Za-z0-9-]*)$", cleaned, re.I)
    if m:
        agent = extract_agent_name(m.group(1)) or extract_agent_name(m.group(0))
        return {"agent_id": agent, "loan_id": m.group(2)}

    # LoanNumber-AgentName (1899703-RITIKA)
    m = re.match(r"^(\d{4,}[A-Za-z0-9-]*)[-_ ]+([A-Za-z][A-Za-z .'-]{1,})$", cleaned, re.I)
    if m:
        agent = extract_agent_name(m.group(2).strip())
        return {"agent_id": agent, "loan_id": m.group(1)}

    # AgentName-LoanNumber (RITIKA-1899703)
    m = re.match(r"^([A-Za-z][A-Za-z .'-]{1,})[-_ ]+(\d{4,}[A-Za-z0-9-]*)$", cleaned, re.I)
    if m:
        agent = extract_agent_name(m.group(1).strip())
        return {"agent_id": agent, "loan_id": m.group(2)}

    # AgentPrefix12345-Name
    m = re.match(r"^([A-Za-z][A-Za-z]+?)(\d{4,})[-_ ]+([A-Za-z][A-Za-z .'-]*)$", cleaned, re.I)
    if m:
        agent = extract_agent_name(m.group(3).strip())
        return {"agent_id": agent, "loan_id": m.group(2)}

    # Single token: sidd009334 or 23330sidd
    m = re.match(r"^([A-Za-z]{3,20})(\d{4,})$", cleaned)
    if m:
        return {"agent_id": m.group(1), "loan_id": m.group(2)}
    m = re.match(r"^(\d{4,})([A-Za-z]{3,20})$", cleaned)
    if m:
        return {"agent_id": m.group(2), "loan_id": m.group(1)}

    if "_" in cleaned or "-" in cleaned:
        parts = [p.strip() for p in re.split(r"[_-]+", cleaned) if p.strip()]
        loan_id = ""
        agent = ""
        for part in parts:
            loan_match = re.fullmatch(r"(\d{4,}[A-Za-z0-9-]*)", part)
            if loan_match and not loan_id:
                loan_id = loan_match.group(1)
                continue
            name = extract_agent_name(part)
            if name and not agent:
                agent = name
        if agent or loan_id:
            return {"agent_id": agent, "loan_id": loan_id}

    loan_match = re.search(r"\b(\d{4,}[A-Za-z0-9-]*)\b", cleaned)
    if loan_match:
        loan_id = loan_match.group(1)
        left = cleaned[: loan_match.start()].strip(" _-.")
        right = cleaned[loan_match.end() :].strip(" _-.")
        for candidate in (right, left, cleaned):
            if not candidate:
                continue
            agent = extract_agent_name(candidate)
            if agent:
                return {"agent_id": agent, "loan_id": loan_id}
        return {"agent_id": "", "loan_id": loan_id}

    agent = extract_agent_name(cleaned)
    return {"agent_id": agent, "loan_id": ""}


def parse_filename_metadata(filename: str) -> dict[str, str]:
    """Back-compat wrapper used during ingest."""
    parsed = parse_agent_loan_from_filename(filename)
    agent_id = parsed.get("agent_id") or ""
    loan_id = parsed.get("loan_id") or ""
    if not agent_id and not loan_id:
        stem = _clean_stem(filename)
        return {"agent_id": "Unknown", "loan_id": "Unknown"}
    return {
        "agent_id": agent_id or "Unknown",
        "loan_id": loan_id or "Unknown",
    }
