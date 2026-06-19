#!/usr/bin/env bash
# HTTPS for api.care.verbilab.com on EC2 (required before Amplify can proxy to API).
#
# PREREQ — DNS (wherever verbilab.com is managed):
#   Type A   Name: api.care   Value: 13.62.231.72   TTL: 300
# Wait 5–15 min, then run on EC2:
#   bash deploy/setup-https-ec2.sh

set -euo pipefail
DOMAIN="${CARE_API_DOMAIN:-api.care.verbilab.com}"

echo "=== HTTPS setup for ${DOMAIN} ==="

if command -v yum >/dev/null 2>&1; then
  sudo yum install -y nginx certbot python3-certbot-nginx 2>/dev/null || {
    sudo yum install -y nginx
    sudo yum install -y certbot python3-certbot-nginx
  }
elif command -v apt-get >/dev/null 2>&1; then
  sudo apt-get update -y
  sudo apt-get install -y nginx certbot python3-certbot-nginx
fi

sudo tee /etc/nginx/conf.d/care-api.conf >/dev/null <<EOF
server {
    listen 80;
    server_name ${DOMAIN};

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

sudo nginx -t
sudo systemctl enable nginx 2>/dev/null || true
sudo systemctl restart nginx 2>/dev/null || sudo nginx -s reload

echo "Checking DNS for ${DOMAIN}..."
if ! getent hosts "${DOMAIN}" >/dev/null 2>&1; then
  echo "WARNING: ${DOMAIN} does not resolve yet. Add DNS A record → this EC2 public IP, then re-run certbot."
fi

echo "Requesting Let's Encrypt certificate..."
sudo certbot --nginx -d "${DOMAIN}" --non-interactive --agree-tos -m theverbilab@gmail.com --redirect || {
  echo ""
  echo "Certbot failed. Common fixes:"
  echo "  1) DNS A record: ${DOMAIN} → $(curl -sf http://169.254.169.254/latest/meta-data/public-ipv4 2>/dev/null || echo 'EC2_PUBLIC_IP')"
  echo "  2) EC2 Security Group: allow inbound TCP 80 and 443"
  echo "  3) Re-run: sudo certbot --nginx -d ${DOMAIN}"
  exit 1
}

echo ""
echo "HTTPS OK — test:"
echo "  curl -s https://${DOMAIN}/api/health"
curl -sf "https://${DOMAIN}/api/health" | python3 -m json.tool || true
echo ""
echo "Update EC2 .env:"
echo "  PUBLIC_API_URL=https://${DOMAIN}"
echo "  CARE_CORS_ORIGINS=https://care.verbilab.com,http://localhost:5173"
echo ""
echo "Amplify → Environment variables:"
echo "  VITE_API_URL=https://${DOMAIN}"
echo "Then redeploy Amplify (keep only SPA rewrite rule for /index.html)."
