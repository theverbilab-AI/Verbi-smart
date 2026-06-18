#!/usr/bin/env bash
# Start CARE API on EC2 (no Docker). Run from care-backend/: bash deploy/start-ec2.sh
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

if [[ ! -d .venv ]]; then
  echo "Missing .venv — run: python3 -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt"
  exit 1
fi

if [[ ! -f .env ]]; then
  echo "Missing .env — run: cp deploy/.env.example .env && nano .env"
  exit 1
fi

# shellcheck disable=SC1091
source .venv/bin/activate
export PORT=5000
mkdir -p uploads exports

pkill -f "gunicorn app:app" 2>/dev/null || true
sleep 1

nohup gunicorn app:app -c gunicorn.conf.py --bind "0.0.0.0:${PORT}" > gunicorn.log 2>&1 &
sleep 4

if curl -sf "http://127.0.0.1:${PORT}/api/health" >/dev/null; then
  echo "OK — http://127.0.0.1:${PORT}/api/health"
  curl -s "http://127.0.0.1:${PORT}/api/health" | python3 -m json.tool
else
  echo "FAILED — last 40 lines of gunicorn.log:"
  tail -40 gunicorn.log
  exit 1
fi
