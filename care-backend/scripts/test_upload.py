#!/usr/bin/env python3
"""Upload a wav file locally and poll until processed."""
import sys
import time
import requests

WAV = r"c:\Users\SIDDHANTH REMMA\Downloads\addadef1-cb9b-4e54-90c4-94a3b81135f6.wav"
BASE = "http://127.0.0.1:5000"


def main():
    print("health", requests.get(f"{BASE}/api/health", timeout=5).json())
    for creds in (
        {"email": "theverbilab@gmail.com", "password": "care@2025"},
        {"email": "admin@care.ai", "password": "care@2025"},
    ):
        r = requests.post(f"{BASE}/api/auth/login", json=creds, timeout=10)
        if r.ok:
            token = r.json()["token"]
            break
    else:
        print("login failed")
        sys.exit(1)

    with open(WAV, "rb") as f:
        up = requests.post(
            f"{BASE}/api/v1/calls/ingest",
            headers={"Authorization": f"Bearer {token}"},
            files={"file": ("1899703-RITIKA.wav", f, "audio/wav")},
            data={"agent_id": "RITIKA", "loan_id": "1899703"},
            timeout=60,
        )
    print("upload", up.status_code, up.text[:300])
    if not up.ok:
        sys.exit(1)

    cid = up.json()["call_id"]
    print("call_id", cid)
    for i in range(60):
        time.sleep(5)
        c = requests.get(f"{BASE}/api/v1/calls/{cid}", timeout=15).json()
        st = c.get("status")
        oa = c.get("opening_audit") or {}
        if isinstance(oa, str):
            oa = {}
        print(
            f"[{i*5:3d}s] status={st} score={c.get('score')} "
            f"ptp={c.get('ptp_detected')} disp={c.get('disposition')} rpc={oa.get('rpc_confirmed')}"
        )
        if c.get("error"):
            print(" error:", c["error"][:200])
        if st in ("processed", "failed"):
            if st == "processed":
                print("grade", c.get("grade"))
                print("breakdown", c.get("scores_breakdown"))
                print("ai_detection", c.get("ai_detection"))
                print("transcript_len", len(c.get("transcript") or ""))
                print(f"view http://localhost:5175/calls/{cid}")
            break


if __name__ == "__main__":
    main()
