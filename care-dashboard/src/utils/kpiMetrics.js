/**
 * Verbicare PRD §6.1–6.3 KPI aggregations.
 * Excludes senior-marked KPIs: PTP Conversion/Broken, DPD, Best Call Time,
 * Promise Reliability, Audit Coverage %, Collection Effectiveness Rate.
 */

const PARAMS = [
  { key: "A1_opening", label: "Opening", max: 2 },
  { key: "A2_case_knowledge", label: "Case Knowledge", max: 2 },
  { key: "A3_probing", label: "Probing", max: 3, critical: true },
  { key: "A4_negotiation", label: "Negotiation", max: 3, critical: true },
  { key: "A5_commitment_ptp", label: "Commitment / PTP", max: 3, critical: true },
  { key: "A6_closing", label: "Closing", max: 2 },
  { key: "A7_professionalism", label: "Professionalism", max: 3, critical: true },
  { key: "A8_call_handling", label: "Call Handling", max: 1 },
  { key: "A9_troubleshooting", label: "Troubleshooting", max: 1 },
];

export { PARAMS };

function processed(calls) {
  return (calls || []).filter((c) => c.status === "processed");
}

function flags(call) {
  const f = call.compliance_flags;
  return Array.isArray(f) ? f.map((x) => String(x).toUpperCase()) : [];
}

function scorePct(call) {
  const n = Number(call.score_pct ?? (call.score != null ? (call.score / 20) * 100 : 0));
  return Number.isFinite(n) ? n : 0;
}

function breakdown(call) {
  return call.scores_breakdown || call.scores || {};
}

function daysAgo(dateStr, days) {
  const d = new Date(dateStr);
  if (Number.isNaN(d.getTime())) return false;
  const cutoff = Date.now() - days * 86400000;
  return d.getTime() >= cutoff;
}

function sentimentTone(call) {
  const s = String(call.agent_sentiment || call.sentiment || "neutral").toLowerCase();
  if (s.includes("positive") || s.includes("good")) return 4;
  if (s.includes("neutral")) return 3;
  if (s.includes("negative") || s.includes("poor")) return 2;
  return 3;
}

function detectLanguage(call) {
  const t = (call.transcript || "").toLowerCase();
  const hindi = (t.match(/\b(haan|nahi|ji|madam|sir|kya|main|aap|rupees|rupaye)\b/g) || []).length;
  const english = (t.match(/\b(the|and|payment|loan|please|thank)\b/g) || []).length;
  if (hindi > english * 1.2) return "Hindi";
  if (english > hindi * 1.2) return "English";
  return hindi && english ? "Mixed" : "Unknown";
}

function hasDispute(call) {
  const d = String(call.disposition || "").toUpperCase();
  return d === "DISPUTE" || flags(call).some((f) => f.includes("DISPUTE"));
}

function hasEscalation(call) {
  const d = String(call.disposition || "").toUpperCase();
  const t = (call.transcript || "").toLowerCase();
  return d.includes("ESCAL") || /escalat|supervisor|manager|complaint/.test(t);
}

function hasAggression(call) {
  return flags(call).some((f) => ["ABUSE", "THREAT", "AGGRESSIVE"].includes(f));
}

function resolved(call) {
  if (call.ptp_detected) return true;
  const d = String(call.disposition || "").toUpperCase();
  return ["PTP", "CALLBACK"].includes(d);
}

function loanRiskScore(callsForLoan) {
  let risk = 0;
  for (const c of callsForLoan) {
    const rl = String(c.risk_level || "LOW").toUpperCase();
    if (rl === "HIGH") risk += 40;
    else if (rl === "MEDIUM") risk += 20;
    risk += flags(c).length * 5;
    if (!c.ptp_detected && String(c.disposition || "").toUpperCase() === "NO_PTP") risk += 10;
    risk += Math.max(0, 50 - scorePct(c)) * 0.3;
  }
  return Math.min(100, Math.round(risk / Math.max(callsForLoan.length, 1)));
}

/** §6.1 Agent-level KPIs (no PTP Conversion / PTP Broken) */
export function buildAgentKpis(calls) {
  const list = processed(calls);
  const byAgent = new Map();

  for (const call of list) {
    const agent = call.agent_id || call.agent_name || "Unknown";
    const row = byAgent.get(agent) || {
      agent_id: agent,
      calls_audited: 0,
      score_sum: 0,
      critical_fail: 0,
      flags: 0,
      resolved: 0,
      tone_sum: 0,
      lang: { Hindi: 0, English: 0, Mixed: 0, Unknown: 0 },
      scores_7d: [],
      scores_30d: [],
      param_sums: Object.fromEntries(PARAMS.map((p) => [p.key, 0])),
      param_counts: Object.fromEntries(PARAMS.map((p) => [p.key, 0])),
      a4_sum: 0,
      a4_count: 0,
    };
    row.calls_audited += 1;
    const pct = scorePct(call);
    row.score_sum += pct;
    if (call.critical_fail) row.critical_fail += 1;
    row.flags += flags(call).length;
    if (resolved(call)) row.resolved += 1;
    row.tone_sum += sentimentTone(call);
    const lang = detectLanguage(call);
    row.lang[lang] = (row.lang[lang] || 0) + 1;

    const uploaded = call.processed_at || call.uploaded_at;
    if (uploaded && daysAgo(uploaded, 7)) row.scores_7d.push(pct);
    if (uploaded && daysAgo(uploaded, 30)) row.scores_30d.push(pct);

    const bd = breakdown(call);
    for (const p of PARAMS) {
      const v = bd[p.key];
      if (v != null && v !== "") {
        row.param_sums[p.key] += Number(v);
        row.param_counts[p.key] += 1;
      }
    }
    const a4 = bd.A4_negotiation;
    if (a4 != null && a4 !== "") {
      row.a4_sum += Number(a4);
      row.a4_count += 1;
    }
    byAgent.set(agent, row);
  }

  return [...byAgent.values()].map((r) => {
    const n = Math.max(r.calls_audited, 1);
    const parameter_scores = {};
    for (const p of PARAMS) {
      const c = r.param_counts[p.key];
      parameter_scores[p.key] = c ? Math.round((r.param_sums[p.key] / c) * 10) / 10 : null;
    }
    const avg7 = r.scores_7d.length ? average(r.scores_7d) : null;
    const avg30 = r.scores_30d.length ? average(r.scores_30d) : null;
    const prior = avg30 != null && avg7 != null ? avg30 - avg7 : null;
    const dominantLang = Object.entries(r.lang).sort((a, b) => b[1] - a[1])[0]?.[0] || "—";

    return {
      agent_id: r.agent_id,
      calls_audited: r.calls_audited,
      overall_quality_score: Math.round(r.score_sum / n),
      parameter_scores,
      critical_fail_rate: Math.round((r.critical_fail / n) * 100),
      compliance_flags_count: r.flags,
      call_resolution_rate: Math.round((r.resolved / n) * 100),
      objection_handling_score: r.a4_count
        ? Math.round((r.a4_sum / r.a4_count / 3) * 100)
        : null,
      tone_score: Math.round((r.tone_sum / n) * 10) / 10,
      language_adherence_pct: Math.round(((r.lang[dominantLang] || 0) / n) * 100),
      language_primary: dominantLang,
      trend_score_7d: avg7 != null ? Math.round(avg7) : "—",
      trend_score_30d: avg30 != null ? Math.round(avg30) : "—",
      trend_delta: prior != null ? `${prior >= 0 ? "+" : ""}${Math.round(prior)}` : "—",
    };
  }).sort((a, b) => b.overall_quality_score - a.overall_quality_score);
}

/** §6.2 Customer / loan-level KPIs (no DPD, no Best Call Time) */
export function buildCustomerKpis(calls) {
  const list = processed(calls);
  const byLoan = new Map();

  for (const call of list) {
    const loan = call.loan_id || "Unknown";
    const row = byLoan.get(loan) || {
      loan_id: loan,
      total_calls_received: 0,
      sentiments: [],
      ptp_history: [],
      dispute: false,
      escalation: false,
      aggression: false,
      languages: [],
      objection_sum: 0,
      objection_count: 0,
      last_contacted: null,
      calls: [],
    };
    row.total_calls_received += 1;
    row.calls.push(call);
    row.sentiments.push({
      date: call.processed_at || call.uploaded_at,
      sentiment: call.agent_sentiment || "neutral",
      disposition: call.disposition,
      score_pct: scorePct(call),
    });
    if (call.ptp_detected) {
      row.ptp_history.push({
        date: call.ptp_date || call.processed_at || call.uploaded_at,
        amount: call.ptp_amount,
        mode: call.ptp_mode,
        call_id: call.id,
      });
    }
    if (hasDispute(call)) row.dispute = true;
    if (hasEscalation(call)) row.escalation = true;
    if (hasAggression(call)) row.aggression = true;
    row.languages.push(detectLanguage(call));
    const a4 = breakdown(call).A4_negotiation;
    if (a4 != null) {
      row.objection_sum += Number(a4);
      row.objection_count += 1;
    }
    const ts = call.processed_at || call.uploaded_at;
    if (ts && (!row.last_contacted || ts > row.last_contacted)) {
      row.last_contacted = ts;
      row.last_outcome = call.disposition;
    }
    byLoan.set(loan, row);
  }

  return [...byLoan.values()].map((r) => {
    const langCounts = {};
    for (const l of r.languages) langCounts[l] = (langCounts[l] || 0) + 1;
    const langPref = Object.entries(langCounts).sort((a, b) => b[1] - a[1])[0]?.[0] || "—";
    return {
      loan_id: r.loan_id,
      total_calls_received: r.total_calls_received,
      call_sentiment_history: r.sentiments.slice(-10),
      ptp_history: r.ptp_history,
      outstanding_loan_amount: "—",
      dispute_flag: r.dispute ? "Yes" : "No",
      escalation_flag: r.escalation ? "Yes" : "No",
      aggression_abuse_flag: r.aggression ? "Yes" : "No",
      language_preference: langPref,
      objection_handling_score: r.objection_count
        ? Math.round((r.objection_sum / r.objection_count / 3) * 100)
        : "—",
      risk_score: loanRiskScore(r.calls),
      last_contacted: r.last_contacted
        ? new Date(r.last_contacted).toLocaleString()
        : "—",
      last_outcome: r.last_outcome || "—",
    };
  }).sort((a, b) => b.total_calls_received - a.total_calls_received);
}

/** §6.3 Portfolio KPIs (no Audit Coverage, Collection Effectiveness, Promise Reliability) */
export function buildPortfolioKpis(calls) {
  const all = calls || [];
  const list = processed(all);
  const total = all.length;
  const n = Math.max(list.length, 1);
  const scores = list.map(scorePct);
  const avgQuality = scores.length ? Math.round(average(scores)) : 0;
  const withFlags = list.filter((c) => flags(c).length > 0).length;
  const ptpCount = list.filter((c) => c.ptp_detected).length;

  const byAgent = buildAgentKpis(all);
  const topAgents = byAgent.slice(0, 10);

  const loanRows = buildCustomerKpis(all);
  const avgRisk =
    loanRows.length
      ? Math.round(average(loanRows.map((l) => l.risk_score)))
      : 0;

  return {
    total_calls_processed: total,
    average_quality_score: avgQuality,
    ptp_rate: Math.round((ptpCount / n) * 100),
    compliance_breach_rate: Math.round((withFlags / n) * 100),
    risk_score_portfolio: avgRisk,
    last_contacted_any: list.length
      ? new Date(
          Math.max(
            ...list.map((c) => new Date(c.processed_at || c.uploaded_at || 0).getTime())
          )
        ).toLocaleString()
      : "—",
    top_performing_agents: topAgents,
  };
}

function average(arr) {
  if (!arr.length) return 0;
  return arr.reduce((a, b) => a + b, 0) / arr.length;
}
