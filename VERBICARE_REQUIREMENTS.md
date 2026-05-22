# Verbicare Changes — CARE implementation status

Source: *Verbicare Changes doc.pdf* (client feedback).

## Implemented in this release (`verbicare-v10`)

| Requirement | Status |
|-------------|--------|
| Dashboard filters: agent, date range, disposition | Done (`Dashboardpage.jsx`) |
| KPI Tracker tab below Dashboard | Done (`/kpis`, Sidebar) |
| A1–A9 rubric scoring (rule-based override of LLM) | Done (`scoring_rules.py`) |
| Sequential gating: A2–A6 = 0 if A1 = 0 on collections calls | Done |
| Non-collections / wrong-number cap (max 4/20, NOT_COLLECTIONS) | Done |
| RPC_MISSED removed when RPC confirmed | Done (`fix_rpc_compliance_flags`) |
| Opening audit: disclaimer, intro, name, RPC checklist | Done (UI + `analysis.opening_audit`) |
| Fuller transcript diarization (no summarize, higher token limit) | Done (`processor.py`) |
| Filename `AgentName_LoanNumber.wav` parsing | Done (`parse_filename_metadata`) |
| Recording playback via API proxy (S3 CORS safe) | Done (`playback-proxy-v9`) |
| Audio speed controls 0.75x–2x | Done (`LiveAiAudit.jsx`) |
| Agent/Customer transcript bifurcation | Done (Sarvam + LLM/heuristic) |

## Requires re-upload / re-process

Old calls keep legacy scores and flags until processed again with the new pipeline.

## KPI Tracker (PRD §6.1–6.3)

**Implemented** in `/kpis` with three tabs (see `kpiMetrics.js`).

**Excluded per senior (yellow highlights):**
- PTP Conversion Rate, PTP Broken Rate (agent)
- DPD, Best Call Time (customer)
- Promise Reliability Score, Audit Coverage %, Collection Effectiveness Rate (portfolio)

**Deferred (needs LMS or audio analytics):**
- Outstanding loan amount (LMS), AHT, talk ratio, dead air, overtalk, empathy, coaching sessions

## Planned (PRD / doc — not in this release)

- Agent Coaching Module (playlists, sessions, gamification)
- Sentiment timeline chart
- Click parameter → jump to transcript evidence
- Dashboards 8.1–8.5 (live ops command centre, executive portfolio, etc.)

## Deploy checklist

1. Push `main` → Railway + Vercel auto-deploy
2. `/api/health` → `build` contains `verbicare-v10`
3. Upload test call `AgentName_123456.wav`
4. Verify opening checklist, score cap on non-collections, audio plays
