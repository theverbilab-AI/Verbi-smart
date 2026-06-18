"""Gunicorn config — reads PORT from the environment (no shell $PORT expansion)."""
import os
from pathlib import Path

try:
    from dotenv import load_dotenv

    load_dotenv(Path(__file__).resolve().parent / ".env")
except ImportError:
    pass

_port = os.environ.get("PORT", "5000")
# Railway misconfiguration can set PORT to the literal string "$PORT".
if not str(_port).isdigit():
    print(f"[gunicorn] Invalid PORT={_port!r}, using 5000", flush=True)
    _port = "5000"

bind = f"0.0.0.0:{_port}"
workers = max(1, int(os.environ.get("GUNICORN_WORKERS", "1")))
threads = 4
timeout = 120
accesslog = "-"
errorlog = "-"
