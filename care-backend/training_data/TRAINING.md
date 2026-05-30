# CARE Scoring Training Guide

CARE does **not** fine-tune model weights today. Training means **few-shot examples** injected into the Sarvam LLM scoring prompt, plus **deterministic rules** in `scoring_rules.py` that always win for RPC, PTP, third party, and compliance.

## What runs on each call

```
Audio → Sarvam STT → Agent/Customer bifurcation (Sarvam LLM)
     → Scoring prompt + 2 similar few-shot examples (from this folder)
     → Sarvam LLM JSON
     → Hybrid rule engine overrides (scoring_rules.py)
     → Saved to DB
```

## Few-shot file

| Item | Value |
|------|--------|
| Path | `care-backend/training_data/scoring_examples.jsonl` |
| Env override | `SCORING_TRAINING_FILE` |
| Format | One JSON object per line |

Each line:

```json
{
  "id": "golden-rpc-yes-tell-me",
  "tags": ["rpc", "opening", "collections"],
  "transcript": "Agent: ...\nCustomer: ...",
  "expected_json": { "scores": {...}, "disposition": "...", ... }
}
```

At scoring time, the 2 most similar examples (by tags + transcript tokens) are appended to the prompt.

## Seed examples

### 1. Curated golden set (no DB required)

```bash
cd care-backend
python scripts/seed_scoring_examples.py --golden
```

Adds 8 scenarios: RPC, PTP, third party safe/breach, app issue, hardship, wrong number, Marathi opening.

### 2. Best calls from your database

```bash
python scripts/seed_scoring_examples.py --from-db --min-score-pct 70 --max-examples 12
```

Or via API (super_admin):

```http
POST /api/v1/training/scoring/seed-from-calls
Authorization: Bearer <token>
Content-Type: application/json

{ "min_score_pct": 70, "max_examples": 12, "merge": true }
```

### 3. Add one QA-reviewed call manually

```http
POST /api/v1/training/scoring/add-example
{ "call_id": "CALL-XXXX", "tags": ["ptp", "rpc"] }
```

Optional `"override": { ... }` if QA corrected the expected JSON.

### 4. List current examples

```http
GET /api/v1/training/scoring/examples
```

## ECS / production

1. Run `seed_scoring_examples.py --golden` locally and commit `scoring_examples.jsonl`, **or**
2. Mount `training_data/` on ECS and run seed after deploy, **or**
3. Call `POST /api/v1/training/scoring/seed-from-calls` once after enough calls are processed.

Redeploy backend so the file is in the container image.

## Future: real model fine-tuning (not implemented)

If you move beyond few-shot + rules:

| Phase | Work |
|-------|------|
| 1. Dataset | 500–2000 calls with QA-reviewed transcripts + gold JSON (RPC, PTP, disposition, scores) |
| 2. Split | 80/10/10 train/val/test; stratify by disposition and language |
| 3. Format | JSONL instruction pairs: `{ "input": transcript, "output": expected_json }` |
| 4. Fine-tune | Sarvam fine-tune API (when available) or open model (Llama/Mistral) on GPU |
| 5. Evaluate | RPC accuracy, PTP F1, disposition accuracy vs holdout; never drop rule overrides for compliance |
| 6. Deploy | Separate model id in `SARVAM_CHAT_MODEL`; keep `scoring_rules.py` as safety layer |

**Recommendation:** Keep hybrid architecture even after fine-tuning — rules for compliance, model for nuance.

## Maintenance

- Re-seed from DB monthly after QA reviews high-score calls.
- Add golden examples when new failure patterns appear (new Hindi phrases, new product).
- Run `python scripts/test_scoring_hybrid.py` before changing examples or rules.
