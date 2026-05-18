#!/usr/bin/env bash
# CARE backend on Ubuntu EC2 (Docker + ffmpeg)
# Usage on a fresh instance:
#   sudo apt-get update && sudo apt-get install -y git
#   git clone https://github.com/siddhanth88/Verbilab_CARE.git
#   cd Verbilab_CARE/care-backend
#   cp deploy/.env.example .env && nano .env
#   bash deploy/ec2-setup.sh

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

if [[ ! -f .env ]]; then
  echo "Create .env first: cp deploy/.env.example .env && edit values"
  exit 1
fi

echo "[1/4] Installing Docker (if needed)..."
if ! command -v docker >/dev/null 2>&1; then
  curl -fsSL https://get.docker.com | sudo sh
  sudo usermod -aG docker "$USER" || true
  echo "Log out and back in so 'docker' works without sudo, then re-run this script."
fi

if docker compose version >/dev/null 2>&1; then
  COMPOSE="docker compose"
elif command -v docker-compose >/dev/null 2>&1; then
  COMPOSE="docker-compose"
else
  sudo apt-get install -y docker-compose-plugin || sudo apt-get install -y docker-compose
  COMPOSE="docker compose"
fi

echo "[2/4] Building image (includes ffmpeg)..."
sudo $COMPOSE build --no-cache

echo "[3/4] Starting API on port 5000..."
sudo $COMPOSE down 2>/dev/null || true
sudo $COMPOSE up -d

echo "[4/4] Health check..."
sleep 5
curl -sf "http://127.0.0.1:5000/api/health" | python3 -m json.tool || {
  echo "Health check failed. Logs:"
  sudo $COMPOSE logs --tail=80
  exit 1
}

PUBLIC_IP="$(curl -sf http://169.254.169.254/latest/meta-data/public-ipv4 2>/dev/null || echo 'YOUR_EC2_PUBLIC_IP')"
echo ""
echo "CARE API is running."
echo "  Local:  http://127.0.0.1:5000/api/health"
echo "  Public: http://${PUBLIC_IP}:5000/api/health"
echo ""
echo "Next steps:"
echo "  1) EC2 Security Group: allow inbound TCP 5000 (or 80/443 if using nginx)"
echo "  2) Netlify env: VITE_API_URL=http://${PUBLIC_IP}:5000"
echo "  3) Redeploy Netlify frontend"
