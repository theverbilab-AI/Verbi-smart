# VERBICARE — Local End-to-End Test
Started: 2026-06-25 14:19:27
RULES_ONLY_SCORING=1  SARVAM_KEY=set

## 1. Collections QA (real audio)

--- Collections: AFILAPLPL15148-RITA.wav (11.3s) ---
  PASS  [AFILAPLPL15148-RITA.wav] processed (status=processed)
  PASS  [AFILAPLPL15148-RITA.wav] transcript present
  PASS  [AFILAPLPL15148-RITA.wav] speaker attribution produced turns
  PASS  [AFILAPLPL15148-RITA.wav] both speakers attributed OR review flagged
  PASS  [AFILAPLPL15148-RITA.wav] every turn has confidence
  PASS  [AFILAPLPL15148-RITA.wav] PTP detection produced a definite result
  PASS  [AFILAPLPL15148-RITA.wav] disposition set
  PASS  [AFILAPLPL15148-RITA.wav] summary non-empty
  PASS  [AFILAPLPL15148-RITA.wav] summary not a prompt leak
  PASS  [AFILAPLPL15148-RITA.wav] review_required present (bool)
    score=5/20 grade=Poor disp=NO_PTP ptp=0 review=False

--- Collections: 1982389-MANSI.mp3 (22.5s) ---
  PASS  [1982389-MANSI.mp3] processed (status=processed)
  PASS  [1982389-MANSI.mp3] transcript present
  PASS  [1982389-MANSI.mp3] speaker attribution produced turns
  PASS  [1982389-MANSI.mp3] both speakers attributed OR review flagged
  PASS  [1982389-MANSI.mp3] every turn has confidence
  PASS  [1982389-MANSI.mp3] PTP detection produced a definite result
  PASS  [1982389-MANSI.mp3] disposition set
  PASS  [1982389-MANSI.mp3] summary non-empty
  PASS  [1982389-MANSI.mp3] summary not a prompt leak
  PASS  [1982389-MANSI.mp3] review_required present (bool)
    score=15/20 grade=Good disp=NO_PTP ptp=0 review=True

--- Collections: 1899703-RITIKA.wav.wav (32.5s) ---
  PASS  [1899703-RITIKA.wav.wav] processed (status=processed)
  PASS  [1899703-RITIKA.wav.wav] transcript present
  PASS  [1899703-RITIKA.wav.wav] speaker attribution produced turns
  PASS  [1899703-RITIKA.wav.wav] both speakers attributed OR review flagged
    NOTE: single-speaker attribution -> review_required=True (safe fallback)
  PASS  [1899703-RITIKA.wav.wav] every turn has confidence
  PASS  [1899703-RITIKA.wav.wav] PTP detection produced a definite result
  PASS  [1899703-RITIKA.wav.wav] disposition set
  PASS  [1899703-RITIKA.wav.wav] summary non-empty
  PASS  [1899703-RITIKA.wav.wav] summary not a prompt leak
  PASS  [1899703-RITIKA.wav.wav] review_required present (bool)
    score=12/20 grade=Needs Improvement disp=LANGUAGE_ISSUE ptp=0 review=True

## 2. Sales QA (real audio, sales mode)

--- Sales: 1986509-GAURI.mp4 ---
  PASS  [1986509-GAURI.mp4] all 16 KPIs present
  PASS  [1986509-GAURI.mp4] score out of 100 (0..100)
  PASS  [1986509-GAURI.mp4] total_pct present (0..100)
  PASS  [1986509-GAURI.mp4] no hallucinated KPI (evidence backs every scored KPI)
  PASS  [1986509-GAURI.mp4] Not-Done KPIs cite no-evidence reason
  PASS  [1986509-GAURI.mp4] summary.executive_summary present
  PASS  [1986509-GAURI.mp4] summary.strengths present
  PASS  [1986509-GAURI.mp4] summary.missed_opportunities present
  PASS  [1986509-GAURI.mp4] summary.coaching_suggestions present
  PASS  [1986509-GAURI.mp4] summary.fatal_errors present
  PASS  [1986509-GAURI.mp4] summary.sales_probability present
  PASS  [1986509-GAURI.mp4] summary.customer_intent present
  PASS  [1986509-GAURI.mp4] recommendations present
  PASS  [1986509-GAURI.mp4] review_required present (bool)
    (real non-sales audio) scored=5.0/100 done/partial KPIs=3 review=True
    score=5.0/100 grade=Poor prob=medium intent=medium review=True

## 2b. Sales engine on real (non-sales) transcripts — no-hallucination proof

--- Sales: AFILAPLPL15148-RITA.wav as-sales ---
  PASS  [AFILAPLPL15148-RITA.wav as-sales] all 16 KPIs present
  PASS  [AFILAPLPL15148-RITA.wav as-sales] score out of 100 (0..100)
  PASS  [AFILAPLPL15148-RITA.wav as-sales] total_pct present (0..100)
  PASS  [AFILAPLPL15148-RITA.wav as-sales] no hallucinated KPI (evidence backs every scored KPI)
  PASS  [AFILAPLPL15148-RITA.wav as-sales] Not-Done KPIs cite no-evidence reason
  PASS  [AFILAPLPL15148-RITA.wav as-sales] summary.executive_summary present
  PASS  [AFILAPLPL15148-RITA.wav as-sales] summary.strengths present
  PASS  [AFILAPLPL15148-RITA.wav as-sales] summary.missed_opportunities present
  PASS  [AFILAPLPL15148-RITA.wav as-sales] summary.coaching_suggestions present
  PASS  [AFILAPLPL15148-RITA.wav as-sales] summary.fatal_errors present
  PASS  [AFILAPLPL15148-RITA.wav as-sales] summary.sales_probability present
  PASS  [AFILAPLPL15148-RITA.wav as-sales] summary.customer_intent present
  PASS  [AFILAPLPL15148-RITA.wav as-sales] recommendations present
  PASS  [AFILAPLPL15148-RITA.wav as-sales] review_required present (bool)
    (real non-sales audio) scored=0.0/100 done/partial KPIs=0 review=True
    score=0.0/100 grade=Poor prob=medium intent=medium review=True

--- Sales: 1982389-MANSI.mp3 as-sales ---
  PASS  [1982389-MANSI.mp3 as-sales] all 16 KPIs present
  PASS  [1982389-MANSI.mp3 as-sales] score out of 100 (0..100)
  PASS  [1982389-MANSI.mp3 as-sales] total_pct present (0..100)
  PASS  [1982389-MANSI.mp3 as-sales] no hallucinated KPI (evidence backs every scored KPI)
  PASS  [1982389-MANSI.mp3 as-sales] Not-Done KPIs cite no-evidence reason
  PASS  [1982389-MANSI.mp3 as-sales] summary.executive_summary present
  PASS  [1982389-MANSI.mp3 as-sales] summary.strengths present
  PASS  [1982389-MANSI.mp3 as-sales] summary.missed_opportunities present
  PASS  [1982389-MANSI.mp3 as-sales] summary.coaching_suggestions present
  PASS  [1982389-MANSI.mp3 as-sales] summary.fatal_errors present
  PASS  [1982389-MANSI.mp3 as-sales] summary.sales_probability present
  PASS  [1982389-MANSI.mp3 as-sales] summary.customer_intent present
  PASS  [1982389-MANSI.mp3 as-sales] recommendations present
  PASS  [1982389-MANSI.mp3 as-sales] review_required present (bool)
    (real non-sales audio) scored=5.0/100 done/partial KPIs=3 review=True
    score=5.0/100 grade=Poor prob=low intent=low review=True

--- Sales: 1899703-RITIKA.wav.wav as-sales ---
  PASS  [1899703-RITIKA.wav.wav as-sales] all 16 KPIs present
  PASS  [1899703-RITIKA.wav.wav as-sales] score out of 100 (0..100)
  PASS  [1899703-RITIKA.wav.wav as-sales] total_pct present (0..100)
  PASS  [1899703-RITIKA.wav.wav as-sales] no hallucinated KPI (evidence backs every scored KPI)
  PASS  [1899703-RITIKA.wav.wav as-sales] Not-Done KPIs cite no-evidence reason
  PASS  [1899703-RITIKA.wav.wav as-sales] summary.executive_summary present
  PASS  [1899703-RITIKA.wav.wav as-sales] summary.strengths present
  PASS  [1899703-RITIKA.wav.wav as-sales] summary.missed_opportunities present
  PASS  [1899703-RITIKA.wav.wav as-sales] summary.coaching_suggestions present
  PASS  [1899703-RITIKA.wav.wav as-sales] summary.fatal_errors present
  PASS  [1899703-RITIKA.wav.wav as-sales] summary.sales_probability present
  PASS  [1899703-RITIKA.wav.wav as-sales] summary.customer_intent present
  PASS  [1899703-RITIKA.wav.wav as-sales] recommendations present
  PASS  [1899703-RITIKA.wav.wav as-sales] review_required present (bool)
    (real non-sales audio) scored=3.0/100 done/partial KPIs=2 review=True
    score=3.0/100 grade=Poor prob=low intent=unknown review=True

## 2c. Sales engine on synthetic positive sales call

--- Sales: synthetic GOOD_CALL ---
  PASS  [synthetic GOOD_CALL] all 16 KPIs present
  PASS  [synthetic GOOD_CALL] score out of 100 (0..100)
  PASS  [synthetic GOOD_CALL] total_pct present (0..100)
  PASS  [synthetic GOOD_CALL] no hallucinated KPI (evidence backs every scored KPI)
  PASS  [synthetic GOOD_CALL] Not-Done KPIs cite no-evidence reason
  PASS  [synthetic GOOD_CALL] summary.executive_summary present
  PASS  [synthetic GOOD_CALL] summary.strengths present
  PASS  [synthetic GOOD_CALL] summary.missed_opportunities present
  PASS  [synthetic GOOD_CALL] summary.coaching_suggestions present
  PASS  [synthetic GOOD_CALL] summary.fatal_errors present
  PASS  [synthetic GOOD_CALL] summary.sales_probability present
  PASS  [synthetic GOOD_CALL] summary.customer_intent present
  PASS  [synthetic GOOD_CALL] recommendations present
  PASS  [synthetic GOOD_CALL] review_required present (bool)
    score=82.0/100 grade=Good prob=medium intent=low review=False
  PASS  [synthetic] positive call scores >= 60%

## 3. Regression / consistency (process vs read vs reprocess)

--- Consistency: AFILAPLPL15148-RITA.wav ---
  PASS  [AFILAPLPL15148-RITA.wav] read API grade stable
  PASS  [AFILAPLPL15148-RITA.wav] reprocess no exception
  PASS  [AFILAPLPL15148-RITA.wav] reprocess grade stable

--- Consistency: 1986509-GAURI.mp4 ---
  PASS  [1986509-GAURI.mp4] read API grade stable
  PASS  [1986509-GAURI.mp4] read API sales score stable
  PASS  [1986509-GAURI.mp4] reprocess no exception
  PASS  [1986509-GAURI.mp4] reprocess grade stable

## Result
PASSED: 108
FAILED: 0