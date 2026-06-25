import { useState } from "react";

const STATUS_STYLES = {
  Done: "bg-emerald-900/50 text-emerald-300 border-emerald-700",
  Partial: "bg-amber-900/40 text-amber-300 border-amber-700",
  "Not Done": "bg-slate-800 text-slate-400 border-slate-600",
  "Fatal Error": "bg-red-900/60 text-red-300 border-red-700",
  None: "bg-slate-800 text-slate-500 border-slate-700",
};

const PROB_STYLES = {
  high: "text-emerald-300",
  medium: "text-amber-300",
  low: "text-slate-400",
  unknown: "text-slate-500",
};

function confColor(conf) {
  if (conf == null) return "text-slate-500";
  if (conf >= 0.75) return "text-emerald-300";
  if (conf >= 0.6) return "text-amber-300";
  return "text-red-300";
}

function StatChip({ label, value, valueClass }) {
  return (
    <div className="rounded-xl bg-slate-900/60 border border-slate-700 px-4 py-3">
      <p className="text-[11px] uppercase tracking-wider text-slate-500 mb-1">{label}</p>
      <p className={`text-lg font-bold ${valueClass || "text-slate-100"}`}>{value}</p>
    </div>
  );
}

function SummaryList({ title, items, accent }) {
  if (!items || items.length === 0) return null;
  return (
    <div className="glass-card rounded-xl p-5">
      <h3 className={`text-sm font-semibold uppercase mb-3 ${accent}`}>{title}</h3>
      <ul className="space-y-2">
        {items.map((it, i) => (
          <li key={i} className="text-sm text-slate-300 leading-relaxed">• {it}</li>
        ))}
      </ul>
    </div>
  );
}

export default function SalesAuditPanel({ call }) {
  const [open, setOpen] = useState(null);
  const audit = call?.analysis?.sales_kpi || {};
  const kpis = audit.kpis || [];
  const summary = audit.summary || {};

  if (!kpis.length) {
    return (
      <div className="glass-card rounded-xl p-6 text-center text-slate-400 mb-4">
        Sales audit not available for this call.
      </div>
    );
  }

  const scored = kpis.filter((k) => k.id !== "fatal");
  const fatal = kpis.find((k) => k.id === "fatal");
  const totalPct = audit.total_pct ?? 0;
  const totalScore = audit.total_score ?? 0;
  const prob = audit.sales_probability || "unknown";
  const intent = audit.customer_intent || "unknown";

  return (
    <div className="space-y-4 mb-4">
      {/* Header strip — Sales-specific, not the Collections layout */}
      <div className="glass-card rounded-xl p-5">
        <div className="flex items-center justify-between flex-wrap gap-3 mb-4">
          <div>
            <p className="text-[11px] uppercase tracking-wider text-cyan-400 font-semibold">
              Sales QA Audit
            </p>
            <h2 className="text-2xl font-bold text-slate-100">
              {totalScore}<span className="text-slate-500 text-lg"> / 100</span>
              <span className="text-slate-400 text-base ml-2">({totalPct}%)</span>
            </h2>
          </div>
          <span className="px-4 py-1.5 rounded-full border border-cyan-700 bg-cyan-950/40 text-cyan-200 text-sm font-semibold">
            {audit.grade || "—"}
          </span>
        </div>

        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
          <StatChip label="Sales Probability" value={prob} valueClass={PROB_STYLES[prob]} />
          <StatChip label="Customer Intent" value={intent} valueClass={PROB_STYLES[intent]} />
          <StatChip
            label="Avg Confidence"
            value={`${Math.round((audit.avg_confidence ?? 0) * 100)}%`}
          />
          <StatChip
            label="Review"
            value={audit.review_required ? "Required" : "Auto-approved"}
            valueClass={audit.review_required ? "text-amber-300" : "text-emerald-300"}
          />
        </div>
      </div>

      {/* Review required banner */}
      {audit.review_required && (
        <div className="bg-amber-950/30 border border-amber-800/50 rounded-xl p-4">
          <p className="text-sm font-semibold text-amber-300 mb-1">⚠ Review required</p>
          <ul className="text-xs text-amber-200/80 space-y-0.5">
            {(audit.review_reasons || ["Low confidence — manual QA recommended."]).map((r, i) => (
              <li key={i}>• {r}</li>
            ))}
          </ul>
        </div>
      )}

      {/* Fatal error banner */}
      {fatal?.fatal_triggered && (
        <div className="bg-red-900/30 border border-red-700 rounded-xl p-4">
          <p className="text-sm font-semibold text-red-300 mb-1">⛔ Fatal / misleading statement detected</p>
          <ul className="text-xs text-red-200/80 space-y-0.5">
            {(fatal.all_evidence || []).map((e, i) => (
              <li key={i}>• “{e}”</li>
            ))}
          </ul>
        </div>
      )}

      {/* Weighted KPI table */}
      <div className="glass-card rounded-xl p-5">
        <h3 className="text-sm font-semibold text-slate-400 uppercase mb-4">
          Weighted KPI Scorecard
        </h3>
        <div className="space-y-1.5">
          <div className="grid grid-cols-[1fr_auto_auto_auto] gap-3 px-2 pb-2 text-[11px] uppercase tracking-wider text-slate-500 border-b border-slate-700">
            <span>KPI</span>
            <span className="text-right w-16">Score</span>
            <span className="text-right w-24">Status</span>
            <span className="text-right w-14">Conf.</span>
          </div>
          {scored.map((k) => {
            const isOpen = open === k.id;
            const pct = k.max ? (k.score / k.max) * 100 : 0;
            return (
              <div key={k.id} className="rounded-lg hover:bg-slate-800/40 transition-colors">
                <button
                  type="button"
                  onClick={() => setOpen(isOpen ? null : k.id)}
                  className="w-full grid grid-cols-[1fr_auto_auto_auto] gap-3 items-center px-2 py-2 text-left"
                >
                  <span className="min-w-0">
                    <span className="text-sm text-slate-200 flex items-center gap-2">
                      <span className="text-slate-500 text-xs">{isOpen ? "▾" : "▸"}</span>
                      {k.name}
                      <span className="text-[10px] text-slate-500">({k.weight})</span>
                    </span>
                    <span className="block h-1 mt-1 ml-5 bg-slate-700 rounded-full overflow-hidden max-w-[220px]">
                      <span
                        className="block h-full rounded-full bg-cyan-500"
                        style={{ width: `${pct}%` }}
                      />
                    </span>
                  </span>
                  <span className="text-right w-16 text-sm font-medium text-slate-200">
                    {k.score}/{k.max}
                  </span>
                  <span className="text-right w-24">
                    <span
                      className={`text-[10px] font-semibold px-2 py-0.5 rounded-full border ${
                        STATUS_STYLES[k.status] || STATUS_STYLES["Not Done"]
                      }`}
                    >
                      {k.status}
                    </span>
                  </span>
                  <span className={`text-right w-14 text-xs font-medium ${confColor(k.confidence)}`}>
                    {Math.round((k.confidence ?? 0) * 100)}%
                  </span>
                </button>

                {isOpen && (
                  <div className="px-2 pb-3 ml-5 space-y-2">
                    <p className="text-xs text-slate-400">{k.reason}</p>
                    {k.evidence && (
                      <div className="text-xs text-slate-300 bg-slate-900/60 border border-slate-700 rounded-md px-3 py-2">
                        <span className="text-slate-500">Evidence: </span>“{k.evidence}”
                      </div>
                    )}
                    {Array.isArray(k.subparams) && k.subparams.length > 0 && (
                      <div className="space-y-1">
                        {k.subparams.map((sp, i) => (
                          <div key={i} className="flex items-center justify-between text-xs">
                            <span className={sp.done ? "text-slate-300" : "text-slate-500"}>
                              {sp.done ? "✓" : "○"} {sp.name}
                              {sp.note && <span className="text-slate-600 italic ml-1">({sp.note})</span>}
                            </span>
                            <span className="text-slate-500">{sp.marks}/{sp.max}</span>
                          </div>
                        ))}
                      </div>
                    )}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      </div>

      {/* Executive summary */}
      {summary.executive_summary && (
        <div className="glass-card rounded-xl p-5">
          <h3 className="text-sm font-semibold text-slate-300 uppercase mb-2">Executive Summary</h3>
          <p className="text-sm text-slate-400 leading-relaxed">{summary.executive_summary}</p>
        </div>
      )}

      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <SummaryList title="✓ Strengths" items={summary.strengths} accent="text-emerald-400" />
        <SummaryList title="✗ Missed Opportunities" items={summary.missed_opportunities} accent="text-red-400" />
        <SummaryList title="💡 Coaching Suggestions" items={summary.coaching_suggestions} accent="text-cyan-400" />
        <SummaryList title="⛔ Fatal Errors" items={summary.fatal_errors} accent="text-orange-400" />
      </div>

      {Array.isArray(audit.recommendations) && audit.recommendations.length > 0 && (
        <div className="bg-cyan-950/30 border border-cyan-800/50 rounded-xl p-5">
          <h3 className="text-sm font-semibold text-cyan-400 uppercase mb-3">Recommendations</h3>
          <ul className="space-y-2">
            {audit.recommendations.map((r, i) => (
              <li key={i} className="text-sm text-slate-300">• {r}</li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
