#!/usr/bin/env bash
# Redeploy CARE backend on EC2 (no Docker).
# Run on the server: cd ~/Verbilab_CARE/care-backend && bash deploy/redeploy-ec2.sh
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
REPO="$(cd "$ROOT/.." && pwd)"
cd "$REPO"

echo "=== CARE redeploy ==="
echo "Repo: $REPO"

if [[ -d .git ]]; then
  echo "[1/5] git pull..."
  git stash push -m "ec2-redeploy-$(date +%s)" 2>/dev/null || true
  git pull origin main
else
  echo "[1/5] skip git (not a git repo)"
fi

cd "$ROOT"

if [[ ! -f .env ]]; then
  echo "ERROR: missing $ROOT/.env — copy from deploy/.env.example and edit first."
  exit 1
fi

echo "[2/5] Python venv..."
PY=python3
if command -v python3.11 >/dev/null 2>&1; then
  PY=python3.11
elif command -v python3.12 >/dev/null 2>&1; then
  PY=python3.12
fi
echo "  Using $($PY --version 2>&1)"

if [[ ! -d .venv ]]; then
  $PY -m venv .venv
fi
# shellcheck disable=SC1091
source .venv/bin/activate

echo "[3/5] pip install..."
pip install -q --upgrade pip
pip install -q -r requirements.txt

echo "[4/5] restart gunicorn..."
export PORT=5000
mkdir -p uploads exports
pkill -f "gunicorn app:app" 2>/dev/null || true
sleep 2

if [[ -f gunicorn.conf.py ]]; then
  nohup gunicorn app:app -c gunicorn.conf.py --bind "0.0.0.0:${PORT}" > gunicorn.log 2>&1 &
else
  nohup gunicorn app:app --bind "0.0.0.0:${PORT}" --workers 1 --timeout 120 > gunicorn.log 2>&1 &
fi
sleep 5

echo "[5/5] health check..."
if curl -sf "http://127.0.0.1:${PORT}/api/health" | python3 -m json.tool; then
  PUBLIC_IP="$(curl -sf http://169.254.169.254/latest/meta-data/public-ipv4 2>/dev/null || echo 'YOUR_EC2_IP')"
  echo ""
  echo "Redeploy OK"
  echo "  Local:  http://127.0.0.1:${PORT}/api/health"
  echo "  Public: http://${PUBLIC_IP}/api/health"
  if command -v nginx >/dev/null 2>&1; then
    sudo nginx -t 2>/dev/null && sudo nginx -s reload 2>/dev/null || true
  fi
else
  echo "Redeploy FAILED — gunicorn.log:"
  tail -50 gunicorn.log
  exit 1
fi
