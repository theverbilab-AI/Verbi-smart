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
Set `VITE_API_URL` to your live backend URL (not Railway if you moved to ECS).
