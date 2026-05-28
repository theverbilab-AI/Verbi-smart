# CARE backend deploy (ECS + ECR)

## Automatic (GitHub Actions)

On every push to `main` under `care-backend/**`:

1. [Actions → Deploy backend to ECR](https://github.com/siddhanth88/Verbilab_CARE/actions/workflows/deploy-ecr.yml)
2. Or **Run workflow** manually (workflow_dispatch)

**Required GitHub repo secrets** (Settings → Secrets → Actions):

| Secret | IAM needs |
|--------|-----------|
| `AWS_ACCESS_KEY_ID` | `verbilab-care` deploy user |
| `AWS_SECRET_ACCESS_KEY` | same |

IAM policy must include at least: `ecr:*` (or GetAuthorizationToken + push), `ecs:UpdateService`, `ecs:DescribeServices`.

If **Login to Amazon ECR** fails: wrong region, missing ECR repo, or keys lack `ecr:GetAuthorizationToken`.

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
