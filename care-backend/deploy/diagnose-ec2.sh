#!/usr/bin/env bash
# Run on EC2: bash deploy/diagnose-ec2.sh
set -u
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

echo "=== CARE EC2 diagnose ==="
echo "Host: $(hostname)"
echo ""

echo "[1] .env exists?"
test -f .env && echo "  yes" || { echo "  MISSING .env"; exit 1; }
grep -q "YOUR_RDS" .env 2>/dev/null && echo "  WARNING: .env still has YOUR_RDS placeholders"
grep -q "DATABASE_URL=" .env && echo "  DATABASE_URL set" || echo "  WARNING: no DATABASE_URL"
echo ""

echo "[2] Python venv?"
test -x .venv/bin/python && .venv/bin/python --version || echo "  MISSING .venv — run: python3 -m venv .venv && pip install -r requirements.txt"
echo ""

echo "[3] Gunicorn process?"
ps aux | grep -E "[g]unicorn app:app" || echo "  NOT RUNNING"
echo ""

echo "[4] Listening ports (5000 / 8080)?"
(ss -lntp 2>/dev/null || netstat -lntp 2>/dev/null) | grep -E ':5000|:8080' || echo "  nothing on 5000 or 8080"
echo ""

echo "[5] RDS / DB import test..."
if test -x .venv/bin/python; then
  .venv/bin/python <<'PY' || true
import os, sys
from dotenv import load_dotenv
load_dotenv()
url = os.getenv("DATABASE_URL", "")
if not url or "YOUR_RDS" in url:
    print("  SKIP — fix DATABASE_URL in .env first")
    sys.exit(0)
try:
    import psycopg2
    conn = psycopg2.connect(url, connect_timeout=8)
    conn.close()
    print("  RDS connect: OK")
except Exception as e:
    print("  RDS connect: FAILED —", e)
try:
    from database import init_db
    init_db()
    print("  init_db(): OK")
except Exception as e:
    print("  init_db(): FAILED —", e)
PY
fi
echo ""

echo "[6] Local health curl..."
curl -sf "http://127.0.0.1:5000/api/health" && echo "" || echo "  FAIL on :5000"
curl -sf "http://127.0.0.1/api/health" && echo "" || echo "  FAIL on :80 (nginx)"
echo ""

echo "[7] Last gunicorn.log lines..."
tail -25 gunicorn.log 2>/dev/null || echo "  no gunicorn.log"
echo ""

echo "[8] Nginx error log (if readable)..."
sudo tail -10 /var/log/nginx/error.log 2>/dev/null || echo "  (cannot read nginx log)"
echo ""
echo "=== Fix: bash deploy/start-ec2.sh ==="
