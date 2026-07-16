# VerbiSmart (CARE)

Call audit platform — collections / sales QA.

**Local path:** `c:\verbilab-projects\VerbiSmart`  
**GitHub:** https://github.com/theverbilab-AI/Verbi-smart

> VerbiVoice (voice bot) is a **separate** repo: https://github.com/theverbilab-AI/VerbiVoice

## Production path (live)

```
Upload (dashboard / API)
  → care-backend/app.py
  → care-backend/processor.py  (Sarvam STT + Sarvam diarization)
  → care-backend/scoring_rules.py + QA
  → PostgreSQL / RDS
  → care-dashboard (Amplify)
```

**STT engine:** Sarvam (`SARVAM_API_KEY`, `CARE_USE_DIARIZATION=1`)

**Deploy:** `care-backend/deploy/redeploy-ec2.sh` · Dashboard: `amplify.yml`

## Repo layout

| Path | Purpose |
|------|---------|
| `care-backend/` | Production Flask API and Sarvam pipeline |
| `care-dashboard/` | React UI (Amplify `appRoot`) |
| `poc-stt/` | STT benchmark lab (isolated) |
| `docs/` | Product and security documentation |

## Local dev

```bash
# Backend
cd care-backend && pip install -r requirements.txt && python app.py

# Dashboard
cd care-dashboard && npm install && npm run dev
```

**EC2 (after re-clone):** `cd ~/VerbiSmart/care-backend && bash deploy/redeploy-ec2.sh`
