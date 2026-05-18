import { useState, useEffect, useMemo } from "react";
import { getDashboard, downloadDispositionLoans } from "../services/api";
import { useNavigate } from "react-router-dom";

const DEFAULT_STATS = {
  calls_today: 0,
  processed: 0,
  processing_pct: 0,
  compliance_flags: 0,
  live_calls: 0,
  avg_score: 0,
  ptp_rate: 0,
  audit_coverage: 0,
  ingestion: { direct: 0, google_drive: 0, dialer_webhook: 0, s3: 0 },
  disposition_breakdown: {},
  score_distribution: {},
  agent_performance: [],
  kpis: {},
};

const SCORE_BUCKETS = ["0-20", "21-40", "41-60", "61-80", "81-100"];
const DISPOSITION_LABELS = {
  PTP: "PTP",
  CALLBACK: "Callback",
  DISCONNECTED: "Disconnected",
  PAYMENT_ISSUE: "Payment issue",
  LANGUAGE_ISSUE: "Language issue",
  APP_NOT_WORKING: "App not working",
  FINANCIAL_HARDSHIP: "Financial hardship",
  MEDICAL_ISSUE: "Medical issue",
  DISPUTE: "Dispute",
  THIRD_PARTY: "Third party",
  WRONG_NUMBER: "Wrong number",
  NO_RESPONSE: "No response",
  OTHER: "Other",
};

export default function DashboardPage() {
  const [stats, setStats] = useState(DEFAULT_STATS);
  const [recentCalls, setRecentCalls] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [exporting, setExporting] = useState(null);
  const navigate = useNavigate();

  useEffect(() => {
    let mounted = true;

    const fetchDashboard = async () => {
      try {
        setLoading(true);
        setError(null);
        const data = await getDashboard();
        if (!mounted) return;
        setStats((prev) => ({ ...prev, ...data, ingestion: { ...prev.ingestion, ...(data.ingestion || {}) } }));
        setRecentCalls(data.recent_calls ?? data.calls ?? []);
      } catch (err) {
        console.error("Dashboard fetch failed:", err);
        if (mounted) setError("Could not load dashboard data. Check backend /api/v1/reports/dashboard.");
      } finally {
        if (mounted) setLoading(false);
      }
    };

    fetchDashboard();
    const interval = setInterval(fetchDashboard, 30_000);
    return () => {
      mounted = false;
      clearInterval(interval);
    };
  }, []);

  const derived = useMemo(() => deriveDashboard(stats, recentCalls), [stats, recentCalls]);

  const downloadLoans = async (disposition) => {
    try {
      setExporting(disposition);
      await downloadDispositionLoans(disposition);
    } catch (err) {
      console.error("Disposition export failed:", err);
      setError(err.message || "Could not download loan IDs for this disposition.");
    } finally {
      setExporting(null);
    }
  };

  return (
    <div className="p-6 text-white space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold">Dashboard</h1>
          <p className="text-xs text-gray-500 mt-1">CARE · Call Audit & Conduct Risk Engine</p>
        </div>
        {loading && <span className="text-xs text-gray-400 animate-pulse">Refreshing…</span>}
      </div>

      {error && (
        <div className="bg-red-900/40 border border-red-700 text-red-300 rounded-lg px-4 py-3 text-sm">
          ⚠ {error}
        </div>
      )}

      <div className="grid grid-cols-2 lg:grid-cols-6 gap-4">
        <KpiCard label="Calls Today" value={derived.callsToday} />
        <KpiCard label="Processed" value={`${derived.processingPct}%`} sub={`${derived.processed} calls`} />
        <KpiCard label="Avg Score" value={`${derived.avgScore}%`} accent={scoreAccent(derived.avgScore)} />
        <KpiCard label="PTP Rate" value={`${derived.ptpRate}%`} accent="text-cyan-300" />
        <KpiCard label="Compliance Flags" value={derived.complianceFlags} accent="text-red-400" />
        <KpiCard label="Live Calls" value={derived.liveCalls} accent="text-green-400" />
      </div>

      <div className="grid grid-cols-1 xl:grid-cols-3 gap-6">
        <Panel title="Disposition Categories" subtitle="Click a category to download all matching loan IDs (portfolio)">
          <BarList
            items={derived.dispositions}
            onClick={(item) => downloadLoans(item.key)}
            exporting={exporting}
            empty="No disposition data yet"
          />
        </Panel>

        <Panel title="Score Distribution" subtitle="Processed calls by score bucket">
          <BarList items={derived.scoreDistribution} empty="No score data yet" />
        </Panel>

        <Panel title="Today's Ingestion" subtitle="Source-wise call intake">
          <div className="space-y-3">
            {[
              { label: "Direct Upload", value: stats.ingestion?.direct || 0 },
              { label: "Google Drive", value: stats.ingestion?.google_drive || 0 },
              { label: "Amazon S3", value: stats.ingestion?.s3 || 0 },
              { label: "Dialer Webhook", value: stats.ingestion?.dialer_webhook || 0 },
            ].map((row) => (
              <div key={row.label} className="flex items-center justify-between">
                <span className="text-sm text-gray-300">{row.label}</span>
                <span className="font-semibold">{row.value}</span>
              </div>
            ))}
          </div>
        </Panel>
      </div>

      <div className="grid grid-cols-1 xl:grid-cols-2 gap-6">
        <Panel title="Agent Performance" subtitle="Average score and call count">
          <AgentTable rows={derived.agentPerformance} navigate={navigate} />
        </Panel>

        <Panel title="AI Detections & Suggestions" subtitle="Latest audit intelligence">
          <DetectionFeed calls={recentCalls} />
        </Panel>
      </div>

      <Panel title="Recent Calls" subtitle="Click a row to open the call detail view">
        <RecentCallsTable calls={recentCalls} navigate={navigate} />
      </Panel>
    </div>
  );
}

function deriveDashboard(stats, calls) {
  const processedCalls = calls.filter((c) => ["processed", "completed"].includes(String(c.status || "").toLowerCase()));
  const callsToday = stats.calls_today ?? calls.length ?? 0;
  const processed = stats.processed ?? processedCalls.length ?? 0;
  const processingPct = stats.processing_pct ?? pct(processed, callsToday || processed || 1);

  const scores = processedCalls
    .map((c) => Number(c.score_pct ?? c.compliance_score ?? c.score))
    .filter((n) => Number.isFinite(n));
  const avgScore = Number(stats.avg_score ?? stats.average_score ?? average(scores) ?? 0);

  const ptpCount = processedCalls.filter((c) => truthy(c.ptp_detected) || normalize(c.disposition) === "PTP").length;
  const ptpRate = Number(stats.ptp_rate ?? pct(ptpCount, processedCalls.length || 1));

  const flagCount = stats.compliance_flags ?? processedCalls.reduce((acc, call) => acc + toArray(call.compliance_flags).length, 0);

  const dispositionMap = { ...(stats.disposition_breakdown || {}) };
  if (!Object.keys(dispositionMap).length) {
    for (const call of processedCalls) {
      const key = normalize(call.disposition || inferDisposition(call));
      dispositionMap[key] = (dispositionMap[key] || 0) + 1;
    }
  }

  const scoreMap = { ...(stats.score_distribution || {}) };
  if (!Object.keys(scoreMap).length) {
    for (const bucket of SCORE_BUCKETS) scoreMap[bucket] = 0;
    for (const score of scores) {
      if (score <= 20) scoreMap["0-20"] += 1;
      else if (score <= 40) scoreMap["21-40"] += 1;
      else if (score <= 60) scoreMap["41-60"] += 1;
      else if (score <= 80) scoreMap["61-80"] += 1;
      else scoreMap["81-100"] += 1;
    }
  }

  const agentMap = new Map();
  for (const call of processedCalls) {
    const agent = call.agent_id || call.agent_name || "Unknown";
    const score = Number(call.score_pct ?? call.score ?? 0);
    const row = agentMap.get(agent) || { agent_id: agent, calls: 0, total: 0, flags: 0, ptp: 0 };
    row.calls += 1;
    row.total += Number.isFinite(score) ? score : 0;
    row.flags += toArray(call.compliance_flags).length;
    row.ptp += truthy(call.ptp_detected) || normalize(call.disposition) === "PTP" ? 1 : 0;
    agentMap.set(agent, row);
  }

  const agentPerformance = stats.agent_performance?.length
    ? stats.agent_performance
    : [...agentMap.values()]
        .map((r) => ({ ...r, avg_score: Math.round(r.total / Math.max(r.calls, 1)), ptp_rate: pct(r.ptp, r.calls) }))
        .sort((a, b) => b.avg_score - a.avg_score)
        .slice(0, 8);

  return {
    callsToday,
    processed,
    processingPct: Math.round(processingPct || 0),
    avgScore: Math.round(avgScore || 0),
    ptpRate: Math.round(ptpRate || 0),
    complianceFlags: flagCount || 0,
    liveCalls: stats.live_calls || 0,
    dispositions: mapToBars(dispositionMap, DISPOSITION_LABELS),
    scoreDistribution: mapToBars(scoreMap),
    agentPerformance,
  };
}

function RecentCallsTable({ calls, navigate }) {
  if (!calls.length) return <p className="text-gray-500 text-sm">No calls processed yet.</p>;

  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="text-gray-500 text-xs uppercase border-b border-gray-700">
            <th className="text-left pb-2 pr-4">File</th>
            <th className="text-left pb-2 pr-4">Agent</th>
            <th className="text-left pb-2 pr-4">Loan</th>
            <th className="text-left pb-2 pr-4">Score</th>
            <th className="text-left pb-2 pr-4">Disposition</th>
            <th className="text-left pb-2 pr-4">Risk</th>
            <th className="text-left pb-2">Status</th>
          </tr>
        </thead>
        <tbody>
          {calls.map((call) => {
            const id = call.id ?? call.call_id;
            const score = call.score_pct ?? call.compliance_score ?? call.score;
            return (
              <tr
                key={id ?? call.filename}
                onClick={() => id && navigate(`/calls/${id}`)}
                className="border-b border-gray-700/50 hover:bg-gray-700/30 transition-colors cursor-pointer"
              >
                <td className="py-2 pr-4 font-mono text-xs text-gray-300 max-w-[260px] truncate">
                  {call.filename ?? call.file_name ?? id}
                </td>
                <td className="py-2 pr-4 text-gray-300">{call.agent_id ?? call.agent_name ?? "—"}</td>
                <td className="py-2 pr-4 text-gray-300">{call.loan_id ?? "—"}</td>
                <td className={`py-2 pr-4 font-bold ${scoreAccent(score)}`}>{score ?? "—"}</td>
                <td className="py-2 pr-4 text-gray-300">{labelDisposition(call.disposition || inferDisposition(call))}</td>
                <td className="py-2 pr-4"><RiskBadge risk={call.risk_level} /></td>
                <td className="py-2"><StatusBadge status={call.status} /></td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function AgentTable({ rows }) {
  if (!rows?.length) return <p className="text-gray-500 text-sm">No agent performance data yet.</p>;
  return (
    <div className="space-y-3">
      {rows.map((row) => (
        <div key={row.agent_id || row.name} className="bg-gray-900/50 rounded-lg p-3">
          <div className="flex items-center justify-between mb-2">
            <span className="font-medium">{row.agent_id || row.name || "Unknown"}</span>
            <span className={`font-bold ${scoreAccent(row.avg_score)}`}>{Math.round(row.avg_score || 0)}%</span>
          </div>
          <div className="grid grid-cols-3 gap-2 text-xs text-gray-400">
            <span>{row.calls || row.calls_audited || 0} calls</span>
            <span>{Math.round(row.ptp_rate || 0)}% PTP</span>
            <span>{row.flags || row.compliance_flags || 0} flags</span>
          </div>
        </div>
      ))}
    </div>
  );
}

function DetectionFeed({ calls }) {
  const rows = calls
    .filter((call) => toArray(call.ai_detection).length || call.ai_suggestion || call.summary)
    .slice(0, 6);

  if (!rows.length) return <p className="text-gray-500 text-sm">No AI detections yet.</p>;

  return (
    <div className="space-y-3">
      {rows.map((call) => (
        <div key={call.id || call.call_id || call.filename} className="bg-gray-900/50 rounded-lg p-3">
          <div className="flex items-center justify-between gap-3">
            <p className="text-sm font-medium truncate">{call.filename || call.id}</p>
            <RiskBadge risk={call.risk_level} />
          </div>
          <p className="text-xs text-cyan-300 mt-2">{toArray(call.ai_detection).join(" · ") || labelDisposition(call.disposition)}</p>
          <p className="text-xs text-gray-400 mt-1 line-clamp-2">{call.ai_suggestion || call.summary}</p>
        </div>
      ))}
    </div>
  );
}

function Panel({ title, subtitle, children }) {
  return (
    <div className="bg-gray-800 rounded-xl p-5">
      <div className="mb-4">
        <h2 className="text-sm font-semibold text-gray-300 uppercase">{title}</h2>
        {subtitle && <p className="text-xs text-gray-500 mt-1">{subtitle}</p>}
      </div>
      {children}
    </div>
  );
}

function BarList({ items, onClick, empty, exporting }) {
  const max = Math.max(...items.map((x) => Number(x.value) || 0), 1);
  if (!items.length || items.every((x) => !x.value)) return <p className="text-gray-500 text-sm">{empty}</p>;

  return (
    <div className="space-y-3">
      {items.map((item) => (
        <button
          key={item.key || item.label}
          type="button"
          onClick={() => onClick?.(item)}
          className={`w-full text-left ${onClick ? "hover:bg-gray-700/30 rounded-lg" : ""}`}
        >
          <div className="flex justify-between text-xs mb-1">
            <span className="text-gray-300">{item.label}</span>
            <span className="text-gray-400">
              {exporting === item.key ? "Downloading…" : item.value}
            </span>
          </div>
          <div className="h-2 bg-gray-900 rounded-full overflow-hidden">
            <div className="h-full bg-cyan-500 rounded-full" style={{ width: `${Math.max(4, (item.value / max) * 100)}%` }} />
          </div>
        </button>
      ))}
    </div>
  );
}

function KpiCard({ label, value, sub, accent = "text-white" }) {
  return (
    <div className="bg-gray-800 rounded-xl p-4 border border-gray-700/50">
      <p className="text-xs text-gray-400 uppercase mb-1">{label}</p>
      <p className={`text-3xl font-bold ${accent}`}>{value}</p>
      {sub && <p className="text-xs text-gray-500 mt-1">{sub}</p>}
    </div>
  );
}

function StatusBadge({ status }) {
  const s = String(status || "uploaded").toLowerCase();
  let cls = "bg-gray-700 text-gray-400";
  if (["processed", "completed"].includes(s)) cls = "bg-green-900/50 text-green-400";
  else if (["processing", "scoring", "transcribing", "fetching"].includes(s)) cls = "bg-yellow-900/50 text-yellow-400";
  else if (s === "failed") cls = "bg-red-900/50 text-red-400";
  return <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${cls}`}>{status || "Uploaded"}</span>;
}

function RiskBadge({ risk }) {
  const r = String(risk || "LOW").toUpperCase();
  const cls = r === "HIGH" ? "bg-red-900/60 text-red-300" : r === "MEDIUM" ? "bg-yellow-900/60 text-yellow-300" : "bg-green-900/50 text-green-300";
  return <span className={`text-[10px] px-2 py-0.5 rounded-full font-semibold ${cls}`}>{r}</span>;
}

function mapToBars(map, labels = {}) {
  return Object.entries(map || {})
    .map(([key, value]) => ({ key: normalize(key), label: labels[normalize(key)] || key, value: Number(value) || 0 }))
    .filter((item) => item.value > 0)
    .sort((a, b) => b.value - a.value);
}

function scoreAccent(score) {
  const n = Number(score);
  if (!Number.isFinite(n)) return "text-gray-400";
  if (n >= 80) return "text-green-400";
  if (n >= 60) return "text-yellow-400";
  return "text-red-400";
}

function normalize(v) {
  return String(v || "OTHER").trim().toUpperCase().replace(/[\s-]+/g, "_");
}

function labelDisposition(v) {
  return DISPOSITION_LABELS[normalize(v)] || String(v || "Other");
}

function pct(part, total) {
  return Math.round((Number(part || 0) / Math.max(Number(total || 0), 1)) * 100);
}

function average(nums) {
  if (!nums.length) return 0;
  return nums.reduce((a, b) => a + b, 0) / nums.length;
}

function truthy(v) {
  return v === true || v === 1 || String(v).toLowerCase() === "true" || String(v) === "1";
}

function toArray(v) {
  if (!v) return [];
  if (Array.isArray(v)) return v.filter(Boolean);
  if (typeof v === "string") {
    try {
      const parsed = JSON.parse(v);
      if (Array.isArray(parsed)) return parsed.filter(Boolean);
    } catch (_e) {
      return v.split(/[;,|]/).map((x) => x.trim()).filter(Boolean);
    }
  }
  return [v];
}

function inferDisposition(call) {
  if (truthy(call.ptp_detected)) return "PTP";
  const ai = toArray(call.ai_detection).join(" ").toUpperCase();
  if (ai.includes("FINANCIAL") || ai.includes("HARDSHIP")) return "FINANCIAL_HARDSHIP";
  if (ai.includes("MEDICAL")) return "MEDICAL_ISSUE";
  const flags = toArray(call.compliance_flags).map(normalize);
  if (flags.includes("WRONG_DISCLOSURE") || flags.includes("THIRD_PARTY_BREACH")) return "THIRD_PARTY";
  if (String(call.status || "").toLowerCase() === "failed") return "OTHER";
  return "OTHER";
}

function csvEscape(v) {
  const s = String(v ?? "");
  return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
}
