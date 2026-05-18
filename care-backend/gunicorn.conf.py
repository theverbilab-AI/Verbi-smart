"""Gunicorn config — reads PORT from the environment (no shell $PORT expansion)."""
import os

_port = os.environ.get("PORT", "8080")
# Railway misconfiguration can set PORT to the literal string "$PORT".
if not str(_port).isdigit():
    print(f"[gunicorn] Invalid PORT={_port!r}, using 8080", flush=True)
    _port = "8080"

bind = f"0.0.0.0:{_port}"
workers = 2
threads = 4
timeout = 120
accesslog = "-"
errorlog = "-"
