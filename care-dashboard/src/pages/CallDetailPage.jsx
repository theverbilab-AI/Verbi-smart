import { useState, useEffect, useCallback } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { getCall, getCallAudioUrl } from "../services/api";
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
    if (pct >= 75) return "bg-green-500";
    if (pct >= 50) return "bg-yellow-500";
    return "bg-red-500";
  };

  const totalColor = (pct) => {
    if (pct >= 80) return "text-green-400";
    if (pct >= 60) return "text-yellow-400";
    return "text-red-400";
  };

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
  const audioSrc = getCallAudioUrl(call.id);

  return (
    <div className="p-6 max-w-4xl mx-auto text-white">
      <button
        onClick={() => navigate(-1)}
        className="text-gray-400 hover:text-white text-sm mb-4 flex items-center gap-1 transition-colors"
      >
        ← Back
      </button>

      <div className="flex items-start justify-between mb-6">
        <div>
          <h1 className="text-xl font-bold font-mono">{call.filename}</h1>
          <p className="text-sm text-gray-400 mt-1">
            ID: {call.id} · Loan: {call.loan_id || "—"} · Uploaded: {new Date(call.uploaded_at).toLocaleString()}
          </p>
          {call.agent_id && <p className="text-sm text-gray-400">Agent: {call.agent_id}</p>}
        </div>
        <span className="text-sm font-medium px-3 py-1 rounded-full bg-gray-700">
          {statusLabel[call.status] ?? call.status}
        </span>
      </div>

      {isProcessing && (
        <div className="bg-gray-800 rounded-xl p-6 text-center mb-6 animate-pulse">
          <p className="text-lg font-medium">{statusLabel[call.status]}</p>
          <p className="text-sm text-gray-400 mt-2">This page will update automatically…</p>
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
          <div className="bg-gray-800 rounded-xl p-5 mb-4">
            <p className="text-sm font-semibold text-gray-300 mb-2">Summary</p>
            <p className="text-sm text-gray-400 leading-relaxed">{call.summary}</p>
            {call.disposition && (
              <p className="text-xs text-cyan-400 mt-2">
                Disposition: {DISPOSITION_LABELS[call.disposition] || call.disposition}
              </p>
            )}
          </div>

          <LiveAiAudit
            call={call}
            audioSrc={audioSrc}
            complianceScore={complianceScore}
            risk={risk}
            totalColor={totalColor}
          />

          <div className="bg-gray-800 rounded-xl p-5 mb-4">
            <h2 className="text-sm font-semibold text-gray-400 uppercase mb-4">Score Breakdown (KPIs)</h2>
            <div className="space-y-3">
              {Object.entries(SCORE_LABELS).map(([key, { label, max, critical }]) => {
                const val = call.scores_breakdown?.[key] ?? 0;
                return (
                  <div key={key}>
                    <div className="flex justify-between text-sm mb-1">
                      <span className="text-gray-300 flex items-center gap-2">
                        {label}
                        {critical && (
                          <span className="text-xs px-1.5 py-0.5 rounded bg-red-900/40 text-red-400 font-semibold">
                            CRITICAL
                          </span>
                        )}
                      </span>
                      <span className="font-medium">{val} / {max}</span>
                    </div>
                    <div className="h-2 bg-gray-700 rounded-full overflow-hidden">
                      <div
                        className={`h-full rounded-full ${scoreColor(val, max)}`}
                        style={{ width: `${(val / max) * 100}%` }}
                      />
                    </div>
                  </div>
                );
              })}
              <div className="pt-2 border-t border-gray-700 flex justify-between text-sm font-bold">
                <span className="text-gray-200">Total Score</span>
                <span className={totalColor(scorePct)}>{rawTotal} / 20 ({scorePct}%)</span>
              </div>
            </div>
          </div>

          {call.ptp_detected && (
            <div className="bg-green-900/20 border border-green-700 rounded-xl p-5 mb-4">
              <h2 className="text-sm font-semibold text-green-400 uppercase mb-3">✅ PTP Secured</h2>
              <div className="grid grid-cols-3 gap-4 text-sm">
                <div>
                  <p className="text-gray-400 mb-1">Amount</p>
                  <p className="font-semibold">{call.ptp_amount ?? "—"}</p>
                </div>
                <div>
                  <p className="text-gray-400 mb-1">Date</p>
                  <p className="font-semibold">{call.ptp_date ?? "—"}</p>
                </div>
                <div>
                  <p className="text-gray-400 mb-1">Mode</p>
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
            <div className="bg-gray-800 rounded-xl p-5 mb-4">
              <h2 className="text-sm font-semibold text-gray-400 uppercase mb-3">⚠ Compliance Flags</h2>
              <div className="flex flex-wrap gap-2">
                {call.compliance_flags.map((flag) => (
                  <span
                    key={flag}
                    className={`text-xs font-semibold px-3 py-1 rounded-full border ${FLAG_STYLES[flag] ?? "bg-gray-700 text-gray-300 border-gray-600"}`}
                  >
                    {flag.replace(/_/g, " ")}
                  </span>
                ))}
              </div>
            </div>
          )}

          <div className="grid grid-cols-2 gap-4 mb-4">
            {call.strengths?.length > 0 && (
              <div className="bg-gray-800 rounded-xl p-5">
                <h2 className="text-sm font-semibold text-green-400 uppercase mb-3">✓ Strengths</h2>
                <ul className="space-y-2">
                  {call.strengths.map((s, i) => (
                    <li key={i} className="text-sm text-gray-300">• {s}</li>
                  ))}
                </ul>
              </div>
            )}
            {call.key_issues?.length > 0 && (
              <div className="bg-gray-800 rounded-xl p-5">
                <h2 className="text-sm font-semibold text-red-400 uppercase mb-3">✗ Key Issues</h2>
                <ul className="space-y-2">
                  {call.key_issues.map((s, i) => (
                    <li key={i} className="text-sm text-gray-300">• {s}</li>
                  ))}
                </ul>
              </div>
            )}
          </div>

          {call.coaching_tip && (
            <div className="bg-blue-900/20 border border-blue-700 rounded-xl p-5 mb-4">
              <h2 className="text-sm font-semibold text-blue-400 uppercase mb-2">💡 Coaching Tip</h2>
              <p className="text-sm text-gray-300">{call.coaching_tip}</p>
            </div>
          )}
        </>
      )}
    </div>
  );
}
