import { useState, useEffect, useCallback } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { getCall } from "../services/api";
import LiveAiAudit from "../components/LiveAiAudit";

const POLL_INTERVAL_MS = 4000;

const SCORE_LABELS = {
  A1_opening:          { label: "A1 · Opening",               max: 2,  critical: false },
  A2_case_knowledge:   { label: "A2 · Case Knowledge",        max: 2,  critical: false },
  A3_probing:          { label: "A3 · Probing",               max: 3,  critical: true  },
  A4_negotiation:      { label: "A4 · Negotiation",           max: 3,  critical: true  },
  A5_commitment_ptp:   { label: "A5 · Commitment / PTP",      max: 3,  critical: true  },
  A6_closing:          { label: "A6 · Closing",               max: 2,  critical: false },
  A7_professionalism:  { label: "A7 · Professionalism",       max: 3,  critical: true  },
  A8_call_handling:    { label: "A8 · Call Handling",         max: 1,  critical: false },
  A9_troubleshooting:  { label: "A9 · Troubleshooting",       max: 1,  critical: false },
};

const FLAG_STYLES = {
  THREAT: "bg-red-900/60 text-red-300 border-red-700",
  RPC_MISSED: "bg-red-900/60 text-red-300 border-red-700",
  FALSE_PROMISE: "bg-orange-900/60 text-orange-300 border-orange-700",
  WRONG_DISCLOSURE: "bg-yellow-900/60 text-yellow-300 border-yellow-700",
  AGGRESSIVE: "bg-red-900/60 text-red-300 border-red-700",
  GDPR_BREACH: "bg-purple-900/60 text-purple-300 border-purple-700",
};

const DISPOSITION_LABELS = {
  PTP: "PTP",
  CALLBACK: "Callback",
  FINANCIAL_HARDSHIP: "Financial hardship",
  MEDICAL_ISSUE: "Medical issue",
  PAYMENT_ISSUE: "Payment issue",
  OTHER: "Other",
};

/**
 * PRD grade bands — neutral cyan/slate theme; red only for real compliance breach.
 */
function getScoreTheme(scorePct, criticalFail, riskLevel, grade) {
  const risk = String(riskLevel || "LOW").toUpperCase();
  const g = String(grade || "").toLowerCase();
  const breach =
    criticalFail &&
    (risk === "HIGH" ||
      g.includes("critical") ||
      scorePct < 20);

  let band, hex, label;

  if (breach) {
    band = "breach";
    hex = "#f97316";
    label = "Compliance review";
  } else if (g.includes("excellent") || scorePct >= 90) {
    band = "excellent";
    hex = "#06b6d4";
    label = grade || "Excellent";
  } else if (g.includes("good") || scorePct >= 70) {
    band = "good";
    hex = "#22d3ee";
    label = grade || "Good";
  } else if (g.includes("needs") || scorePct >= 40) {
    band = "average";
    hex = "#94a3b8";
    label = grade || "Needs Improvement";
  } else {
    band = "poor";
    hex = "#64748b";
    label = grade || "Poor";
  }

  const ambient = `radial-gradient(circle at 10% -5%, ${hex}28 0%, transparent 38%),
         radial-gradient(circle at 90% 5%, ${hex}1a 0%, transparent 42%)`;

  return {
    band,
    label,
    hex,
    accent: "text-cyan-300",
    badgeBg: "bg-slate-800/80 border-slate-600 text-slate-200",
    ring: `0 0 0 1px ${hex}44, 0 0 20px ${hex}22`,
    ambient,
  };
}

export default function CallDetailPage() {
  const { callId } = useParams();
  const navigate = useNavigate();
  const [call, setCall] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  const fetchCall = useCallback(async () => {
    try {
      const data = await getCall(callId);
      setCall(data);
      setError(null);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }, [callId]);

  useEffect(() => {
    fetchCall();
  }, [fetchCall]);

  useEffect(() => {
    const inProgress = ["queued", "transcribing", "scoring", "fetching"];
    if (!call || !inProgress.includes(call.status)) return;
    const t = setTimeout(fetchCall, POLL_INTERVAL_MS);
    return () => clearTimeout(t);
  }, [call, fetchCall]);

  const scoreColor = (score, max) => {
    const pct = (score / max) * 100;
    if (pct >= 75) return "bg-cyan-500";
    if (pct >= 50) return "bg-slate-500";
    return "bg-slate-600";
  };

  const totalColor = () => "text-cyan-300";

  const statusLabel = {
    queued: "⏳ Queued",
    transcribing: "🎙 Transcribing…",
    scoring: "🤖 Scoring…",
    processed: "✅ Processed",
    failed: "❌ Failed",
  };

  if (loading) {
    return <div className="p-8 text-gray-400 text-center">Loading call details…</div>;
  }

  if (error) {
    return <div className="p-8 text-red-400 text-center">Error: {error}</div>;
  }

  const isProcessing = ["queued", "transcribing", "scoring", "fetching"].includes(call.status);
  const rawTotal = Number(call.score ?? 0);
  const scorePct = Number(call.score_pct ?? Math.round((rawTotal / 20) * 100));
  const complianceScore = scorePct;
  const risk = String(call.risk_level || "LOW").toUpperCase();
  const theme = getScoreTheme(scorePct, call.critical_fail, risk, call.grade);
  const isProcessed = call.status === "processed";

  return (
    <div
      className="relative min-h-full transition-[background] duration-700 ease-out"
      style={{ background: isProcessed ? theme.ambient : undefined }}
    >
      {/* Top neon edge */}
      {isProcessed && (
        <div
          className="absolute top-0 left-0 right-0 h-[2px] pointer-events-none"
          style={{
            background: `linear-gradient(90deg, transparent 0%, ${theme.hex} 50%, transparent 100%)`,
            boxShadow: `0 0 16px ${theme.hex}, 0 0 32px ${theme.hex}66`,
          }}
        />
      )}

      <div className="p-6 max-w-4xl mx-auto text-slate-100 relative z-10">
        <button
          onClick={() => navigate(-1)}
          className="text-slate-400 hover:text-cyan-300 text-sm mb-4 flex items-center gap-1 transition-colors"
        >
          ← Back
        </button>

        {/* Header card with glow ring matching score */}
        <div
          className="rounded-2xl p-5 mb-6 transition-shadow duration-700"
          style={{
            background: "rgba(15, 23, 42, 0.65)",
            backdropFilter: "blur(16px)",
            boxShadow: isProcessed ? theme.ring : undefined,
            border: isProcessed ? `1px solid ${theme.hex}33` : "1px solid rgba(51, 65, 85, 0.5)",
          }}
        >
          <div className="flex items-start justify-between gap-4 flex-wrap">
            <div className="min-w-0">
              <h1 className="text-xl font-bold font-mono truncate">{call.filename}</h1>
              <p className="text-sm text-slate-400 mt-1">
                ID: {call.id} · Loan: {call.loan_id || "—"} · Uploaded:{" "}
                {new Date(call.uploaded_at).toLocaleString()}
              </p>
              {call.agent_id && call.agent_id !== "Unknown" && (
                <p className="text-sm text-slate-400">Agent: {call.agent_id}</p>
              )}
            </div>
            <div className="flex items-center gap-3">
              {isProcessed && (
                <div
                  className={`px-4 py-2 rounded-full border text-xs font-bold uppercase tracking-wider ${theme.badgeBg}`}
                  style={{ boxShadow: `0 0 18px ${theme.hex}40` }}
                >
                  <span className="opacity-70 mr-1.5">●</span>
                  {theme.label} · {scorePct}%
                </div>
              )}
              <span className="text-xs font-medium px-3 py-1 rounded-full bg-slate-800 border border-slate-700 whitespace-nowrap">
                {statusLabel[call.status] ?? call.status}
              </span>
            </div>
          </div>

          {/* Compliance breach ribbon — only for real conduct/compliance issues */}
          {isProcessed && call.critical_fail && risk === "HIGH" && (
            <div className="mt-4 -mx-5 -mb-5 px-5 py-2.5 border-t border-orange-800/40 bg-orange-950/20 flex items-center gap-2 text-xs font-semibold uppercase tracking-wider text-orange-200 rounded-b-2xl">
              Compliance review required — conduct or disclosure breach detected
            </div>
          )}
        </div>

      {isProcessing && (
        <div className="glass-card rounded-xl p-6 text-center mb-6 animate-pulse">
          <p className="text-lg font-medium">{statusLabel[call.status]}</p>
          <p className="text-sm text-slate-400 mt-2">This page will update automatically…</p>
        </div>
      )}

      {call.status === "failed" && (
        <div className="bg-red-900/30 border border-red-700 rounded-xl p-4 mb-6">
          <p className="font-medium text-red-300">Processing failed</p>
          <p className="text-sm text-red-400 mt-1">{call.error}</p>
        </div>
      )}

      {call.status === "processed" && (
        <>
          <div className="glass-card rounded-xl p-5 mb-4">
            <p className="text-sm font-semibold text-slate-300 mb-2">Summary</p>
            <p className="text-sm text-slate-400 leading-relaxed">{call.summary}</p>
            {call.disposition && (
              <p className="text-xs text-cyan-400 mt-2">
                Disposition: {DISPOSITION_LABELS[call.disposition] || call.disposition}
              </p>
            )}
          </div>

          <LiveAiAudit
            call={call}
            complianceScore={complianceScore}
            risk={risk}
            totalColor={totalColor}
          />

          <div className="glass-card rounded-xl p-5 mb-4">
            <h2 className="text-sm font-semibold text-slate-400 uppercase mb-4">Score Breakdown (KPIs)</h2>
            <div className="space-y-3">
              {Object.entries(SCORE_LABELS).map(([key, { label, max, critical }]) => {
                const val = call.scores_breakdown?.[key] ?? 0;
                return (
                  <div key={key}>
                    <div className="flex justify-between text-sm mb-1">
                      <span className="text-slate-300 flex items-center gap-2">
                        {label}
                        {critical && (
                          <span className="text-xs px-1.5 py-0.5 rounded bg-slate-700 text-slate-400 font-semibold">
                            KPI
                          </span>
                        )}
                      </span>
                      <span className="font-medium">{val} / {max}</span>
                    </div>
                    <div className="h-2 bg-slate-700 rounded-full overflow-hidden">
                      <div
                        className={`h-full rounded-full ${scoreColor(val, max)}`}
                        style={{ width: `${(val / max) * 100}%` }}
                      />
                    </div>
                  </div>
                );
              })}
              <div
                className="mt-3 pt-3 border-t flex items-center justify-between text-sm font-bold rounded-lg px-3 py-2 -mx-1 transition-colors"
                style={{
                  borderColor: `${theme.hex}55`,
                  background: `linear-gradient(90deg, ${theme.hex}1a 0%, transparent 90%)`,
                }}
              >
                <span className="flex items-center gap-2 text-slate-100">
                  <span
                    className="inline-block w-2 h-2 rounded-full"
                    style={{ background: theme.hex, boxShadow: `0 0 8px ${theme.hex}` }}
                  />
                  Total Score · {theme.label}
                </span>
                <span className={theme.accent + " text-base"}>
                  {rawTotal} / 20 <span className="opacity-70">({scorePct}%)</span>
                </span>
              </div>
            </div>
          </div>

          {call.ptp_detected && (
            <div className="bg-emerald-950/30 border border-emerald-800/50 rounded-xl p-5 mb-4">
              <h2 className="text-sm font-semibold text-emerald-400 uppercase mb-3">✅ PTP Secured</h2>
              <div className="grid grid-cols-3 gap-4 text-sm">
                <div>
                  <p className="text-slate-400 mb-1">Amount</p>
                  <p className="font-semibold">{call.ptp_amount ?? "—"}</p>
                </div>
                <div>
                  <p className="text-slate-400 mb-1">Date</p>
                  <p className="font-semibold">{call.ptp_date ?? "—"}</p>
                </div>
                <div>
                  <p className="text-slate-400 mb-1">Mode</p>
                  <p className="font-semibold">{call.ptp_mode ?? "—"}</p>
                </div>
              </div>
            </div>
          )}

          {call.ptp_detected === false && (
            <div className="bg-red-900/20 border border-red-800 rounded-xl p-4 mb-4">
              <p className="text-sm text-red-400 font-semibold">❌ No PTP Secured — Call ended without commitment</p>
            </div>
          )}

          {call.compliance_flags?.length > 0 && (
            <div className="glass-card rounded-xl p-5 mb-4">
              <h2 className="text-sm font-semibold text-slate-400 uppercase mb-3">⚠ Compliance Flags</h2>
              <div className="flex flex-wrap gap-2">
                {call.compliance_flags.map((flag) => (
                  <span
                    key={flag}
                    className={`text-xs font-semibold px-3 py-1 rounded-full border ${FLAG_STYLES[flag] ?? "bg-slate-700 text-slate-300 border-slate-600"}`}
                  >
                    {flag.replace(/_/g, " ")}
                  </span>
                ))}
              </div>
            </div>
          )}

          <div className="grid grid-cols-2 gap-4 mb-4">
            {call.strengths?.length > 0 && (
              <div className="glass-card rounded-xl p-5">
                <h2 className="text-sm font-semibold text-emerald-400 uppercase mb-3">✓ Strengths</h2>
                <ul className="space-y-2">
                  {call.strengths.map((s, i) => (
                    <li key={i} className="text-sm text-slate-300">• {s}</li>
                  ))}
                </ul>
              </div>
            )}
            {call.key_issues?.length > 0 && (
              <div className="glass-card rounded-xl p-5">
                <h2 className="text-sm font-semibold text-red-400 uppercase mb-3">✗ Key Issues</h2>
                <ul className="space-y-2">
                  {call.key_issues.map((s, i) => (
                    <li key={i} className="text-sm text-slate-300">• {s}</li>
                  ))}
                </ul>
              </div>
            )}
          </div>

          {call.coaching_tip && (
            <div className="bg-cyan-950/30 border border-cyan-800/50 rounded-xl p-5 mb-4">
              <h2 className="text-sm font-semibold text-cyan-400 uppercase mb-2">💡 Coaching Tip</h2>
              <p className="text-sm text-slate-300">{call.coaching_tip}</p>
            </div>
          )}
        </>
      )}
      </div>
    </div>
  );
}
