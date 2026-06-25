/**
 * Sales QA analytics — aggregates the deterministic 16-KPI sales audit
 * (call.analysis.sales_kpi) across calls. Completely independent of the
 * Collections KPI logic in kpiMetrics.js.
 */
import { formatAgentDisplayName } from "./kpiMetrics";

// Mirrors care-backend/audit_modes/sales_kpi.py (weights sum to 100; fatal = 0).
export const SALES_KPI_DEFS = [
  { id: "opening", name: "Opening", weight: 1 },
  { id: "qualifying", name: "Qualifying Questions", weight: 9 },
  { id: "product_knowledge", name: "Product Knowledge", weight: 9 },
  { id: "exemptions", name: "Exemptions Information", weight: 2 },
  { id: "advance_closing", name: "Advance Closing", weight: 5 },
  { id: "zell_training", name: "Zell Training & Deliverables", weight: 16 },
  { id: "pricing", name: "Pricing pitched with benefits", weight: 8 },
  { id: "whatsapp_email", name: "WhatsApp & Email sharing", weight: 3 },
  { id: "referral", name: "Referral", weight: 3 },
  { id: "closing", name: "Closing Sales", weight: 8 },
  { id: "sales_techniques", name: "Sales Techniques", weight: 8 },
  { id: "objection_handling", name: "Objection Handling", weight: 4 },
  { id: "closing_followup", name: "Closing with Follow-up Day", weight: 10 },
  { id: "soft_skills", name: "Soft Skills", weight: 10 },
  { id: "previous_call_notes", name: "Previous Call Notes", weight: 4 },
];

function audit(call) {
  return call?.analysis?.sales_kpi || null;
}

function processed(calls) {
  return (Array.isArray(calls) ? calls : []).filter(
    (c) => String(c.status || "").toLowerCase() === "processed" && audit(c)
  );
}

function round(n) {
  return Math.round(Number.isFinite(n) ? n : 0);
}

function pct(part, total) {
  return total ? round((part / total) * 100) : 0;
}

/** Dashboard-level sales metrics (cards + charts). */
export function buildSalesDashboard(calls) {
  const rows = processed(calls);
  const total = rows.length;

  const scores = rows.map((c) => Number(audit(c).total_pct ?? c.score_pct ?? 0));
  const avgScore = total ? round(scores.reduce((a, b) => a + b, 0) / total) : 0;

  const prob = { high: 0, medium: 0, low: 0 };
  const intent = { high: 0, medium: 0, low: 0, unknown: 0 };
  let reviewCount = 0;
  let fatalCount = 0;

  // Per-KPI average score % across calls (to surface weakest areas).
  const kpiTotals = {};
  for (const def of SALES_KPI_DEFS) kpiTotals[def.id] = { sum: 0, n: 0 };

  for (const c of rows) {
    const a = audit(c);
    const p = String(a.sales_probability || "low").toLowerCase();
    if (p in prob) prob[p] += 1;
    const it = String(a.customer_intent || "unknown").toLowerCase();
    if (it in intent) intent[it] += 1; else intent.unknown += 1;
    if (a.review_required) reviewCount += 1;
    if (a.critical_fail) fatalCount += 1;
    for (const k of a.kpis || []) {
      if (k.id === "fatal" || !(k.id in kpiTotals)) continue;
      const ratio = k.max ? (k.score / k.max) * 100 : 0;
      kpiTotals[k.id].sum += ratio;
      kpiTotals[k.id].n += 1;
    }
  }

  const kpiAverages = SALES_KPI_DEFS.map((def) => {
    const t = kpiTotals[def.id];
    return { id: def.id, name: def.name, weight: def.weight, avgPct: t.n ? round(t.sum / t.n) : 0 };
  });
  const weakest = [...kpiAverages].sort((a, b) => a.avgPct - b.avgPct).slice(0, 6);

  return {
    total,
    avgScore,
    probability: prob,
    intent,
    reviewRate: pct(reviewCount, total),
    fatalCount,
    reviewCount,
    kpiAverages,
    weakest,
    scoreDistribution: scoreBuckets(scores),
  };
}

function scoreBuckets(scores) {
  const buckets = { "0-20": 0, "21-40": 0, "41-60": 0, "61-80": 0, "81-100": 0 };
  for (const s of scores) {
    if (s <= 20) buckets["0-20"] += 1;
    else if (s <= 40) buckets["21-40"] += 1;
    else if (s <= 60) buckets["41-60"] += 1;
    else if (s <= 80) buckets["61-80"] += 1;
    else buckets["81-100"] += 1;
  }
  return buckets;
}

/** Per-agent sales scorecard: avg score + per-KPI averages + review/fatal. */
export function buildSalesAgentKpis(calls) {
  const rows = processed(calls);
  const byAgent = new Map();

  for (const c of rows) {
    const a = audit(c);
    const agent = formatAgentDisplayName(c) || c.agent_id || "Unknown";
    let r = byAgent.get(agent);
    if (!r) {
      r = { agent, calls: 0, scoreSum: 0, review: 0, fatal: 0, kpis: {} };
      for (const def of SALES_KPI_DEFS) r.kpis[def.id] = { sum: 0, n: 0 };
      byAgent.set(agent, r);
    }
    r.calls += 1;
    r.scoreSum += Number(a.total_pct ?? 0);
    if (a.review_required) r.review += 1;
    if (a.critical_fail) r.fatal += 1;
    for (const k of a.kpis || []) {
      if (k.id === "fatal" || !(k.id in r.kpis)) continue;
      r.kpis[k.id].sum += k.max ? (k.score / k.max) * 100 : 0;
      r.kpis[k.id].n += 1;
    }
  }

  return [...byAgent.values()]
    .map((r) => ({
      agent: r.agent,
      calls: r.calls,
      avgScore: r.calls ? round(r.scoreSum / r.calls) : 0,
      reviewRate: pct(r.review, r.calls),
      fatal: r.fatal,
      kpiScores: Object.fromEntries(
        SALES_KPI_DEFS.map((def) => [def.id, r.kpis[def.id].n ? round(r.kpis[def.id].sum / r.kpis[def.id].n) : 0])
      ),
    }))
    .sort((a, b) => b.avgScore - a.avgScore);
}
