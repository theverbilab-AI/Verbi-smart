import { useState, useEffect, useMemo } from "react";
import { getDashboard, downloadDispositionLoans } from "../services/api";
import { useNavigate, useSearchParams } from "react-router-dom";
import {
  BarChart,
  Bar,
  Cell,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  PieChart,
  Pie,
  Legend,
} from "recharts";

const TOP_AGENTS_LIMIT = 8;
const TOP_DETECTIONS_LIMIT = 8;
const TOP_RECENT_CALLS_LIMIT = 10;
const SCORE_BUCKET_COLORS = ["#ef4444", "#f97316", "#f59e0b", "#22c55e", "#06b6d4"];
const DISPOSITION_PALETTE = [
  "#06b6d4", "#22d3ee", "#10b981", "#34d399", "#a78bfa",
  "#f59e0b", "#fb923c", "#f43f5e", "#94a3b8", "#64748b",
];
const INGESTION_PALETTE = {
  "Direct Upload": "#06b6d4",
  "Google Drive": "#22d3ee",
  "Amazon S3": "#10b981",
  "Dialer Webhook": "#a78bfa",
};

const DEFAULT_STATS = {
  calls_today: 0,
  processed: 0,
  processing_pct: 0,
  compliance_flags: 0,
  live_calls: 0,
  avg_score: 0,
  ptp_rate: 0,
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
  const [filters, setFilters] = useState({ from: "", to: "", agent_id: "", disposition: "" });
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const quickFilter = searchParams.get("filter"); // "live" | "flags" | null

  useEffect(() => {
    let mounted = true;

    const fetchDashboard = async () => {
      try {
        setLoading(true);
        setError(null);
        const params = {};
        if (filters.from) params.from = filters.from;
        if (filters.to) params.to = filters.to;
        if (filters.agent_id) params.agent_id = filters.agent_id;
        if (filters.disposition) params.disposition = filters.disposition;
        const data = await getDashboard(params);
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
  }, [filters]);

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

      <div className="flex flex-wrap gap-3 bg-gray-800/60 rounded-xl p-4 border border-gray-700">
        <input type="date" value={filters.from} onChange={(e) => setFilters((f) => ({ ...f, from: e.target.value }))}
          className="bg-gray-700 rounded-lg px-3 py-2 text-sm border border-gray-600" title="From date" />
        <input type="date" value={filters.to} onChange={(e) => setFilters((f) => ({ ...f, to: e.target.value }))}
          className="bg-gray-700 rounded-lg px-3 py-2 text-sm border border-gray-600" title="To date" />
        <input type="text" placeholder="Agent ID" value={filters.agent_id}
          onChange={(e) => setFilters((f) => ({ ...f, agent_id: e.target.value }))}
          className="bg-gray-700 rounded-lg px-3 py-2 text-sm border border-gray-600 min-w-[120px]" />
        <select value={filters.disposition} onChange={(e) => setFilters((f) => ({ ...f, disposition: e.target.value }))}
          className="bg-gray-700 rounded-lg px-3 py-2 text-sm border border-gray-600">
          <option value="">All dispositions</option>
          {Object.entries(DISPOSITION_LABELS).map(([k, v]) => (
            <option key={k} value={k}>{v}</option>
          ))}
        </select>
        <button type="button" onClick={() => setFilters({ from: "", to: "", agent_id: "", disposition: "" })}
          className="text-xs text-cyan-400 hover:text-cyan-300 px-2">Clear filters</button>
      </div>

      <div className="grid grid-cols-2 lg:grid-cols-6 gap-4">
        <KpiCard label="Calls Today" value={derived.callsToday} />
        <KpiCard label="Processed" value={`${derived.processingPct}%`} sub={`${derived.processed} calls`} />
        <KpiCard label="Avg Score" value={`${derived.avgScore}%`} accent={scoreAccent(derived.avgScore)} />
        <KpiCard label="PTP Rate" value={`${derived.ptpRate}%`} accent="text-cyan-300" />
        <KpiCard label="Compliance Flags" value={derived.complianceFlags} accent="text-red-400" />
        <KpiCard label="Live Calls" value={derived.liveCalls} accent="text-green-400" />
      </div>

      <div className="grid grid-cols-1 xl:grid-cols-3 gap-6">
        <Panel
          title="Disposition Categories"
          subtitle="Click a bar to download all matching loan IDs (portfolio)"
        >
          <DispositionChart
            items={derived.dispositions}
            onClick={(item) => downloadLoans(item.key)}
            exporting={exporting}
          />
        </Panel>

        <Panel title="Score Distribution" subtitle="Processed calls by score bucket">
          <ScoreDistributionChart items={derived.scoreDistribution} />
        </Panel>

        <Panel title="Today's Ingestion" subtitle="Source-wise call intake">
          <IngestionChart ingestion={stats.ingestion} />
        </Panel>
      </div>

      <div className="grid grid-cols-1 xl:grid-cols-2 gap-6">
        <Panel
          title="Agent Performance"
          subtitle={`Top ${TOP_AGENTS_LIMIT} agents by average score`}
        >
          <AgentPerformanceChart
            rows={(derived.agentPerformance || []).slice(0, TOP_AGENTS_LIMIT)}
            navigate={navigate}
          />
        </Panel>

        <Panel title="AI Detections & Suggestions" subtitle={`Latest ${TOP_DETECTIONS_LIMIT} flagged calls`}>
          <DetectionFeed calls={recentCalls} limit={TOP_DETECTIONS_LIMIT} />
        </Panel>
      </div>

      <Panel
        title={
          quickFilter === "live"
            ? "Live Calls (in progress)"
            : quickFilter === "flags"
            ? "Calls with Compliance Flags"
            : "Recent Calls"
        }
        subtitle={
          quickFilter
            ? `Filtered view — clear by going back to /dashboard`
            : `Latest ${TOP_RECENT_CALLS_LIMIT} calls — click a row to open the detail view`
        }
      >
        <RecentCallsTable
          calls={filterRecentCalls(recentCalls, quickFilter, TOP_RECENT_CALLS_LIMIT)}
          navigate={navigate}
        />
      </Panel>
    </div>
  );
}

function filterRecentCalls(calls, quickFilter, limit) {
  const list = Array.isArray(calls) ? calls : [];
  const inProgress = new Set(["queued", "fetching", "transcribing", "scoring", "processing"]);
  if (quickFilter === "live") {
    return list.filter((c) => inProgress.has(String(c.status || "").toLowerCase()));
  }
  if (quickFilter === "flags") {
    return list.filter((c) => {
      const f = c.compliance_flags;
      const arr = Array.isArray(f) ? f : [];
      return arr.some((x) => x && String(x).toUpperCase() !== "NONE");
    });
  }
  return list.slice(0, limit);
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

function AgentPerformanceChart({ rows, navigate }) {
  if (!rows?.length) {
    return <p className="text-gray-500 text-sm">No agent performance data yet.</p>;
  }

  const data = rows.map((row) => ({
    name: truncate(row.agent_id || row.name || "Unknown", 18),
    fullName: row.agent_id || row.name || "Unknown",
    score: Math.round(row.avg_score || 0),
    calls: row.calls || row.calls_audited || 0,
    ptp: Math.round(row.ptp_rate || 0),
    flags: row.flags || row.compliance_flags || 0,
  }));

  return (
    <div className="space-y-3">
      <div style={{ width: "100%", height: 36 * data.length + 24 }}>
        <ResponsiveContainer>
          <BarChart
            data={data}
            layout="vertical"
            margin={{ top: 4, right: 36, left: 8, bottom: 4 }}
          >
            <CartesianGrid stroke="#1e293b" strokeDasharray="3 3" horizontal={false} />
            <XAxis
              type="number"
              domain={[0, 100]}
              tick={{ fill: "#64748b", fontSize: 11 }}
              tickFormatter={(v) => `${v}%`}
              axisLine={false}
              tickLine={false}
            />
            <YAxis
              type="category"
              dataKey="name"
              width={140}
              tick={{ fill: "#cbd5e1", fontSize: 12 }}
              axisLine={false}
              tickLine={false}
            />
            <Tooltip content={<ChartTooltip valueLabel="Avg score" valueSuffix="%" />} />
            <Bar
              dataKey="score"
              radius={[0, 6, 6, 0]}
              onClick={(d) => {
                const target = rows.find((r) => (r.agent_id || r.name) === d.fullName);
                if (target?.agent_id) navigate(`/kpis?agent=${encodeURIComponent(target.agent_id)}`);
              }}
              cursor="pointer"
            >
              {data.map((d, i) => (
                <Cell
                  key={i}
                  fill={d.score >= 75 ? "#10b981" : d.score >= 50 ? "#06b6d4" : d.score >= 30 ? "#f59e0b" : "#ef4444"}
                />
              ))}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </div>
      <div className="grid grid-cols-1 gap-1 text-[11px] text-slate-500">
        {data.map((d) => (
          <div key={d.fullName} className="flex justify-between gap-2 px-1">
            <span className="truncate text-slate-400">{d.fullName}</span>
            <span className="whitespace-nowrap">
              {d.calls} calls · {d.ptp}% PTP · {d.flags} flag{d.flags === 1 ? "" : "s"}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}

function DispositionChart({ items, onClick, exporting }) {
  if (!items?.length) return <p className="text-gray-500 text-sm">No disposition data yet.</p>;

  const data = items.slice(0, 8).map((item, i) => ({
    name: item.label,
    key: item.key,
    value: Number(item.value) || 0,
    color: DISPOSITION_PALETTE[i % DISPOSITION_PALETTE.length],
  }));

  return (
    <div style={{ width: "100%", height: Math.max(220, 32 * data.length + 24) }}>
      <ResponsiveContainer>
        <BarChart
          data={data}
          layout="vertical"
          margin={{ top: 4, right: 32, left: 8, bottom: 4 }}
        >
          <CartesianGrid stroke="#1e293b" strokeDasharray="3 3" horizontal={false} />
          <XAxis
            type="number"
            allowDecimals={false}
            tick={{ fill: "#64748b", fontSize: 11 }}
            axisLine={false}
            tickLine={false}
          />
          <YAxis
            type="category"
            dataKey="name"
            width={130}
            tick={{ fill: "#cbd5e1", fontSize: 12 }}
            axisLine={false}
            tickLine={false}
          />
          <Tooltip
            content={<ChartTooltip valueLabel="Calls" exporting={exporting} />}
          />
          <Bar
            dataKey="value"
            radius={[0, 6, 6, 0]}
            onClick={(d) => onClick?.({ key: d.key, label: d.name })}
            cursor={onClick ? "pointer" : "default"}
          >
            {data.map((d, i) => (
              <Cell key={i} fill={d.color} fillOpacity={exporting === d.key ? 0.45 : 1} />
            ))}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}

function ScoreDistributionChart({ items }) {
  if (!items?.length || items.every((it) => !it.value)) {
    return <p className="text-gray-500 text-sm">No score data yet.</p>;
  }

  const data = SCORE_BUCKETS.map((bucket, i) => {
    const found = items.find((it) => it.label === bucket || it.key === bucket);
    return {
      name: bucket,
      value: found ? Number(found.value) || 0 : 0,
      color: SCORE_BUCKET_COLORS[i],
    };
  });

  return (
    <div style={{ width: "100%", height: 240 }}>
      <ResponsiveContainer>
        <BarChart data={data} margin={{ top: 12, right: 12, left: -16, bottom: 0 }}>
          <CartesianGrid stroke="#1e293b" strokeDasharray="3 3" vertical={false} />
          <XAxis dataKey="name" tick={{ fill: "#cbd5e1", fontSize: 11 }} axisLine={false} tickLine={false} />
          <YAxis allowDecimals={false} tick={{ fill: "#64748b", fontSize: 11 }} axisLine={false} tickLine={false} />
          <Tooltip content={<ChartTooltip valueLabel="Calls" />} />
          <Bar dataKey="value" radius={[6, 6, 0, 0]}>
            {data.map((d, i) => (
              <Cell key={i} fill={d.color} />
            ))}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}

function IngestionChart({ ingestion }) {
  const data = [
    { name: "Direct Upload", value: ingestion?.direct || 0 },
    { name: "Google Drive", value: ingestion?.google_drive || 0 },
    { name: "Amazon S3", value: ingestion?.s3 || 0 },
    { name: "Dialer Webhook", value: ingestion?.dialer_webhook || 0 },
  ];
  const total = data.reduce((acc, d) => acc + d.value, 0);

  if (!total) {
    return (
      <div className="space-y-3">
        {data.map((row) => (
          <div key={row.name} className="flex items-center justify-between">
            <span className="text-sm text-slate-300">{row.name}</span>
            <span className="font-semibold text-slate-500">0</span>
          </div>
        ))}
        <p className="text-xs text-slate-500 mt-2">No ingestion today yet.</p>
      </div>
    );
  }

  return (
    <div style={{ width: "100%", height: 240 }}>
      <ResponsiveContainer>
        <PieChart>
          <Pie
            data={data.filter((d) => d.value > 0)}
            dataKey="value"
            nameKey="name"
            cx="50%"
            cy="50%"
            innerRadius={48}
            outerRadius={80}
            paddingAngle={2}
            stroke="#0f172a"
          >
            {data
              .filter((d) => d.value > 0)
              .map((d, i) => (
                <Cell key={i} fill={INGESTION_PALETTE[d.name] || DISPOSITION_PALETTE[i]} />
              ))}
          </Pie>
          <Tooltip content={<ChartTooltip valueLabel="Calls" />} />
          <Legend
            verticalAlign="bottom"
            iconType="circle"
            wrapperStyle={{ fontSize: "11px", color: "#cbd5e1" }}
          />
        </PieChart>
      </ResponsiveContainer>
    </div>
  );
}

function ChartTooltip({ active, payload, valueLabel = "Value", valueSuffix = "" }) {
  if (!active || !payload?.length) return null;
  const item = payload[0];
  return (
    <div className="bg-slate-900/95 border border-slate-700 rounded-lg px-3 py-2 text-xs shadow-xl">
      <p className="text-slate-300 font-semibold mb-0.5">{item.payload.fullName || item.payload.name}</p>
      <p className="text-cyan-300">
        {valueLabel}:{" "}
        <span className="font-bold">
          {item.value}
          {valueSuffix}
        </span>
      </p>
    </div>
  );
}

function truncate(s, n) {
  const str = String(s || "");
  return str.length > n ? str.slice(0, n - 1) + "…" : str;
}

function DetectionFeed({ calls, limit = TOP_DETECTIONS_LIMIT }) {
  const rows = calls
    .filter((call) => toArray(call.ai_detection).length || call.ai_suggestion || call.summary)
    .slice(0, limit);

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
    <div className="glass-card rounded-xl p-5">
      <div className="mb-4">
        <h2 className="text-sm font-semibold text-slate-200 uppercase tracking-wide">{title}</h2>
        {subtitle && <p className="text-xs text-slate-500 mt-1">{subtitle}</p>}
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
