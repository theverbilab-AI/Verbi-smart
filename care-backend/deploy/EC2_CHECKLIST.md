# EC2 deployment checklist (Verbilab CARE)

## 1. Launch EC2 (recommended: **eu-north-1** — same region as S3 bucket)

- Ubuntu 22.04, t3.medium or larger (bulk audio needs RAM + CPU)
- Security group: **443/80** (nginx) or **5000** (direct API), SSH 22 from your IP
- Attach IAM role **or** use access keys in `.env` (user `verbilab-care`)

> Your screenshot showed **us-east-1 with no instances**. Either launch there and set `S3_AUDIO_REGION=eu-north-1`, or launch in **eu-north-1** (Stockholm) next to the bucket.

## 2. Backend on EC2 (recommended: **no Docker**)

Same as your laptop: `Python + gunicorn + ffmpeg`. Docker is **optional**, not required.

```bash
git clone https://github.com/theverbilab-AI/Verbi-smart.git VerbiSmart
cd VerbiSmart/care-backend
cp deploy/.env.example .env
nano .env   # fill DATABASE_URL, JWT_SECRET, SARVAM_API_KEY, AWS keys, SES
bash deploy/ec2-setup-native.sh
```

**Docker alternative** (only if you prefer containers on the server):

```bash
bash deploy/ec2-setup.sh
```

> If `systemctl` says *"System has not been booted with systemd"* — you may be in CloudShell or a container shell, not the EC2 host. Use **EC2 → Connect → EC2 Instance Connect** (browser SSH to `ec2-user@…`), or reboot the instance from the AWS console. Use `service nginx status` or `ps aux | grep nginx` instead of `systemctl`.

Required `.env` keys:

| Variable | Example |
|----------|---------|
| `PUBLIC_API_URL` | `https://api.care.verbilab.com` |
| `S3_AUDIO_REGION` | `eu-north-1` |
| `S3_BUCKET` | `verbilab-care-audio-2026` |
| `AWS_ACCESS_KEY_ID` | IAM user verbilab-care |
| `AWS_SECRET_ACCESS_KEY` | from IAM |
| `GOOGLE_API_KEY` | for Drive bulk folder sync |
| `CARE_CORS_ORIGINS` | `https://care.verbilab.com` |

Health check: `curl http://13.62.231.72/api/health` → `"status":"ok"`, `"db_ok":true`

## Redeploy (after git push from laptop)

On EC2:

```bash
cd ~/VerbiSmart/care-backend
bash deploy/redeploy-ec2.sh
```

Or manual: `git pull` → `source .venv/bin/activate` → `pip install -r requirements.txt` → `bash deploy/start-ec2.sh`

## 3. Nginx + HTTPS (optional)

```bash
sudo cp deploy/nginx-care.conf /etc/nginx/sites-available/care-api
# edit server_name to api.care.verbilab.com
sudo certbot --nginx -d api.care.verbilab.com
```

## 4. Frontend (Amplify / Netlify / Hostinger)

Set build env:

```
VITE_API_URL=https://api.care.verbilab.com
```

**Railway is removed** — do not use `verbilabcare-production.up.railway.app`.

## 5. Google Drive bulk uploads (client workflow)

1. Client shares Drive folder as **Anyone with link**
2. In CARE → Upload → **Drive / URL** tab → paste folder link  
   `https://drive.google.com/drive/folders/FOLDER_ID`
3. All `.mp3/.wav/.m4a` in folder are queued automatically

Requires `GOOGLE_API_KEY` on backend (Google Cloud Console → Drive API enabled).

## 6. S3 ingest (optional)

Clients can upload to `s3://verbilab-care-audio-2026/audio/...`  
CARE → Upload → S3 tab → paste URI.

Only works when EC2 `.env` has valid AWS credentials.

## 7. GitHub Actions → ECR → ECS (alternative to EC2)

See `deploy/DEPLOY.md` for CI deploy to ECS cluster `care-backend`.
