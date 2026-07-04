# Verbilab CARE

Collections call audit platform — production API + dashboard + isolated STT benchmark lab.

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

## POC path (benchmark only — not production)

```
Audio file
  → poc-stt/  (Silero VAD → silence trim → parallel Pyannote + STT)
  → poc-stt/output_schema.py  (normalized JSON)
  → (future) same audit/scoring engine
```

**Goal:** Sub-₹0.20/min STT cost with IndicConformer / Parakeet vs Sarvam baseline.

See [poc-stt/README.md](poc-stt/README.md) for the benchmark pipeline.

## Repo layout

| Path | Purpose |
|------|---------|
| `care-backend/` | Production Flask API and Sarvam pipeline |
| `care-dashboard/` | React UI |
| `poc-stt/` | STT benchmark lab (isolated from uploads) |
| `archive/` | Retired debug scripts, old Whisper GPU POC, legacy deploy configs |
| `docs/` | Product and security documentation |

**Client-facing architecture doc:** [docs/PRODUCT_ARCHITECTURE.md](docs/PRODUCT_ARCHITECTURE.md) (Sarvam, EC2, S3, Amplify, RDS).

## Local dev

```bash
# Backend (production)
cd care-backend && pip install -r requirements.txt && python app.py

# Dashboard
cd care-dashboard && npm install && npm run dev

# POC benchmark (separate venv recommended)
cd poc-stt && pip install -r requirements.txt
```
