# Ollama Voicebot Feasibility — VERBICARE

Last updated: 2026-05-30  
**Scope:** Feasibility and architecture notes only. No voicebot implementation in this phase.

---

## Executive Summary

Running voicebot reasoning on **Ollama** (local/open-weight LLMs) can **reduce recurring inference cost** for clients with high call volume, at the cost of **infrastructure investment**, **latency tuning**, and **model quality trade-offs** vs cloud APIs (OpenAI, Sarvam, etc.).

**Recommendation:** Use Ollama for **non-real-time or semi-real-time** voicebot flows (e.g. IVR assist, post-call summarization, internal QA bots) first. For **sub-second conversational turn-taking**, hybrid architecture (local STT/TTS + cloud LLM or smaller local model) is safer until GPU latency is validated on target hardware.

---

## 1. Cost Reduction Potential

| Factor | Cloud LLM API | Ollama (self-hosted) |
|--------|---------------|----------------------|
| Per-token cost | Ongoing $/1M tokens | Hardware + electricity + ops |
| Scale economics | Linear with usage | Fixed cost amortized over volume |
| Break-even | Low volume favors cloud | High volume (10k+ calls/month) favors local |

Clients with **predictable high volume** and **data residency requirements** benefit most from Ollama.

---

## 2. Suitable Models for Voicebot Reasoning

| Model | Size | Use case | Notes |
|-------|------|----------|-------|
| Llama 3.2 3B | Small | Fast intent + slot filling | Low latency on CPU |
| Qwen2.5 7B | Medium | General dialogue + tool use | Good quality/speed balance |
| Mistral 7B | Medium | Structured responses | Strong instruction following |
| Llama 3.1 8B | Medium | Sales/collections scripts | Needs GPU for real-time |
| DeepSeek-R1 distilled | Medium | Complex reasoning | Higher latency |

For Indian English/Hinglish collections/sales, **fine-tuning or RAG over client scripts** on a 7B model typically outperforms raw 70B cloud calls for domain tasks.

---

## 3. Recommended Architecture

```
Voice input → STT (Sarvam / Whisper local) → Ollama LLM → response logic / state machine → TTS (Piper / Sarvam / ElevenLabs)
                     ↓
              VERBICARE audit pipeline (async)
                     ↓
              CRM sync (LeadSquared, etc.)
```

- **STT:** Keep Sarvam or Whisper for Indian accents; Ollama does not replace STT.
- **LLM:** Ollama hosts the dialogue brain (intent, policy, objection scripts).
- **TTS:** Separate service; cache common phrases to cut latency.
- **Audit:** Record full call → existing VERBICARE upload/score flow unchanged.

---

## 4. Infrastructure Requirements

### Minimum (dev / pilot)
- 16 GB RAM, 4 CPU cores
- Models ≤ 7B quantized (Q4)
- Latency: 2–8 s per turn on CPU

### Production voicebot (recommended)
- **GPU:** NVIDIA T4 (16 GB) or L4 — 1–2 concurrent streams at &lt;1.5 s/token for 7B Q4
- **RAM:** 32 GB system
- **Storage:** 50 GB for models + logs
- **Network:** Low-latency internal VPC; no public exposure of Ollama port

### High availability
- 2+ GPU nodes behind load balancer
- Model warm on startup (avoid cold load)
- Health checks on `/api/tags` (Ollama)

---

## 5. Latency Concerns

| Stage | Typical latency |
|-------|-----------------|
| STT (streaming) | 200–800 ms |
| Ollama 7B (GPU) | 500–2000 ms for 50–150 tokens |
| TTS | 200–600 ms |
| **Total turn** | **1–4 s** (acceptable for many IVR bots; tight for natural conversation) |

Mitigations:
- Stream STT partials; start LLM on stable intent
- Limit `max_tokens`; use concise system prompts
- Pre-compute FAQ/script branches without LLM
- Use smaller models for routing, larger for complex turns only

---

## 6. Security & Privacy Benefits

- **Data stays on client VPC** — no transcript sent to third-party LLM (PCI/collections compliance advantage).
- **Air-gapped option** for regulated NBFCs.
- Audit logs remain under client control.
- Trade-off: client owns patching, model updates, and incident response.

---

## 7. Limitations vs Cloud LLM APIs

| Limitation | Impact |
|------------|--------|
| Model refresh | Manual pull/update vs automatic API upgrades |
| Multilingual quality | Cloud APIs (e.g. Sarvam) may lead on Indian languages until fine-tuned |
| Tool calling / JSON | Smaller local models less reliable; needs validation layer |
| Ops burden | GPU drivers, CUDA, monitoring, failover |
| Scale spikes | Cloud autoscales; local needs capacity planning |

---

## 8. Cost Comparison Points

Estimate monthly for **50,000 bot turns**, ~200 tokens/turn:

- **Cloud:** 50k × 200 = 10M tokens → roughly $20–$200+ depending on provider/tier
- **Self-hosted T4:** EC2 g4dn.xlarge ~$300–500/mo + ops hours
- **Break-even:** Often 100k–500k tokens/month depending on model tier

VERBICARE audit (batch, not real-time) already uses Sarvam; Ollama is complementary for **live bot dialogue**, not a drop-in replacement for batch QA scoring unless quality benchmarks pass.

---

## 9. Integration with VERBICARE

1. Voicebot completes call → audio + metadata webhook to VERBICARE ingest.
2. Same collections/sales audit modes apply.
3. Sales results → LeadSquared via `integrations/crm/leadsquared.py`.
4. Optional: Ollama generates **pre-audit summary** on-device before upload (reduces cloud LLM calls).

---

## 10. Final Recommendation

| Scenario | Recommendation |
|----------|----------------|
| Cost-sensitive client, high volume, data residency | **Proceed with Ollama pilot** on 7B + GPU |
| Real-time natural conversation (&lt;1 s turns) | **Hybrid** — local STT/TTS + cloud LLM or dedicated GPU cluster |
| Collections/sales QA only | **Keep Sarvam/cloud** for audit; Ollama optional for bot dialogue |
| Phase 1 | POC: Ollama + Qwen2.5 7B + Whisper STT + Piper TTS on single GPU box |

**Next steps (when approved):** latency benchmark script, Hinglish eval set, fine-tune on 500 labelled calls, compare WER + QA agreement vs current Sarvam scoring.
