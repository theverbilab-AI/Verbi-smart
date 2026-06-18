#!/usr/bin/env bash
# CARE backend on EC2 — NO Docker. Same as local: Python + gunicorn + ffmpeg.
# Works on Amazon Linux 2023 / Ubuntu 22.04.
#
#   git clone https://github.com/siddhanth88/Verbilab_CARE.git
#   cd Verbilab_CARE/care-backend
#   cp deploy/.env.example .env && nano .env
#   bash deploy/ec2-setup-native.sh

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

if [[ ! -f .env ]]; then
  echo "Create .env first: cp deploy/.env.example .env && nano .env"
  exit 1
fi

echo "[1/5] System packages (git, python, ffmpeg, nginx)..."
if command -v yum >/dev/null 2>&1; then
  sudo yum update -y
  sudo yum install -y git python3 python3-pip ffmpeg nginx
elif command -v apt-get >/dev/null 2>&1; then
  sudo apt-get update -y
  sudo apt-get install -y git python3 python3-venv python3-pip ffmpeg nginx
else
  echo "Unsupported OS — install git, python3, pip, ffmpeg, nginx manually."
  exit 1
fi

echo "[2/5] Python virtualenv + dependencies..."
python3 -m venv .venv
# shellcheck disable=SC1091
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt

echo "[3/5] Nginx reverse proxy (port 80 → 5000)..."
PUBLIC_IP="$(curl -sf http://169.254.169.254/latest/meta-data/public-ipv4 2>/dev/null || echo "_")"
sudo tee /etc/nginx/conf.d/care-api.conf >/dev/null <<EOF
server {
    listen 80 default_server;
    server_name _;

    client_max_body_size 100M;

    location / {
        proxy_pass http://127.0.0.1:5000;
        proxy_http_version 1.1;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_read_timeout 300s;
    }
}
EOF

if command -v systemctl >/dev/null 2>&1 && systemctl is-system-running --quiet 2>/dev/null; then
  sudo systemctl enable nginx
  sudo systemctl restart nginx
elif command -v service >/dev/null 2>&1; then
  sudo service nginx restart || sudo nginx -s reload
else
  sudo nginx -t && sudo nginx -s reload 2>/dev/null || sudo nginx
fi

echo "[4/5] Start gunicorn on port 5000..."
bash deploy/start-ec2.sh
