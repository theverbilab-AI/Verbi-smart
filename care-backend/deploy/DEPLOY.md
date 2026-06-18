# CARE backend deploy (ECS + ECR)

## Option A — GitHub Actions (recommended)

### Step 1 — IAM user for GitHub (one-time)

1. AWS Console → **IAM** → **Users** → create user `github-care-deploy` (or reuse `verbilab-care`).
2. **Attach policy** → Create inline policy → JSON → paste from  
   `care-backend/deploy/github-actions-iam-policy.json`
3. **Security credentials** → **Create access key** → Application running outside AWS → copy **Access key ID** and **Secret**.

> Current CI failure is on **Ensure ECR repository exists** — the key works but needs `ecr:DescribeRepositories`, `ecr:CreateRepository`, and push permissions (included in that JSON).

### Step 2 — GitHub secrets

1. Open https://github.com/siddhanth88/Verbilab_CARE/settings/secrets/actions
2. **New repository secret**:
   - Name: `AWS_ACCESS_KEY_ID` → paste access key
   - Name: `AWS_SECRET_ACCESS_KEY` → paste secret  
3. No quotes, no spaces at end of line.

### Step 3 — Run deploy workflow

1. https://github.com/siddhanth88/Verbilab_CARE/actions/workflows/deploy-ecr.yml
2. **Run workflow** → branch `main` → **Run workflow**
3. Wait until all steps are green (~3–5 min):
   - Ensure ECR repository exists
   - Login to Amazon ECR
   - Build, tag, and push image
   - Force ECS service redeploy

### Few-shot scoring examples (included in image)

Golden examples live in `care-backend/training_data/scoring_examples.jsonl`. They are copied into the Docker image automatically. After deploy, optionally seed from production calls:

```http
POST /api/v1/training/scoring/seed-from-calls
{ "min_score_pct": 70, "max_examples": 12, "merge": true }
```

See `care-backend/training_data/TRAINING.md` for full guide.

### S3 audio (required env on EC2 / ECS)

Bucket lives in **eu-north-1**. EC2/ECS may run in **us-east-1** — that is fine, but you **must** set:

```
S3_AUDIO_REGION=eu-north-1
S3_BUCKET=verbilab-care-audio-2026
AWS_ACCESS_KEY_ID=<verbilab-care key>
AWS_SECRET_ACCESS_KEY=<verbilab-care secret>
```

IAM inline policy for user `verbilab-care`:

```json
{
  "Version": "2012-10-17",
  "Statement": [{
    "Effect": "Allow",
    "Action": ["s3:GetObject", "s3:PutObject", "s3:HeadObject", "s3:ListBucket"],
    "Resource": [
      "arn:aws:s3:::verbilab-care-audio-2026",
      "arn:aws:s3:::verbilab-care-audio-2026/*"
    ]
  }]
}
```

After deploy, reprocess calls so bifurcation + scoring fixes apply to stored transcripts.

### Mail OTP (AWS SES)

See `deploy/SES_OTP.md`. Set on EC2/ECS:

```
AWS_SES_REGION=us-east-1
SES_FROM_EMAIL=theverbilab@gmail.com
SES_FROM_NAME=Verbilab CARE
SES_SMTP_USERNAME=...
SES_SMTP_PASSWORD=...
AUTH_OTP_ENABLED=true
```

Never commit `.env` or SMTP passwords to git.


### Step 4 — Verify

1. ECS → cluster **default** → service **care-backend** → **Running** = **Desired**
2. Hit your API health endpoint (same URL the dashboard uses).
3. Reprocess calls: `POST /api/v1/calls/reprocess` with `{ "limit": 30 }`

---

## Automatic on push

On every push to `main` under `care-backend/**`, the same workflow runs automatically after secrets are set.

## Manual (your PC)

```powershell
aws configure   # use verbilab-care keys, region us-east-1
cd care-backend
.\deploy\deploy.ps1
```

Adjust cluster/service if different:

```powershell
$env:ECS_CLUSTER = "default"
$env:ECS_SERVICE = "care-backend"
.\deploy\deploy.ps1
```

## After deploy

1. ECS console → **care-backend** → wait until **Running** = **Desired**
2. Health: your API `/api/health`
3. **Reprocess** calls so new scoring KPIs apply to existing rows:
   `POST /api/v1/calls/reprocess` with `{ "limit": 30 }`

## Frontend (verbilab.com)

If Amplify/Netlify is connected to `main`, it redeploys on push.  
Set `VITE_API_URL` to your EC2/API URL (e.g. `https://api.care.verbilab.com`). Railway is no longer used.
