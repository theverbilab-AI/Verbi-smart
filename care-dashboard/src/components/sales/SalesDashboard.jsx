import { useMemo } from "react";
import { useNavigate } from "react-router-dom";
import {
  BarChart, Bar, Cell, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer,
  PieChart, Pie, Legend,
} from "recharts";
import { buildSalesDashboard } from "../../utils/salesMetrics";
import { useTheme } from "../../utils/useTheme";
import { getChartTheme } from "../../utils/theme";
import { formatAgentDisplayName } from "../../utils/kpiMetrics";

const SCORE_COLORS = ["#ef4444", "#f97316", "#f59e0b", "#22c55e", "#15803d"];
const PROB_COLORS = { high: "#10b981", medium: "#f59e0b", low: "#ef4444" };

function Card({ label, value, sub, accent }) {
  return (
    <div className="glass-card rounded-xl p-4">
      <p className="text-xs care-muted uppercase mb-1">{label}</p>
      <p className={`text-3xl font-bold ${accent || ""}`} style={!accent ? { color: "var(--care-text-primary)" } : undefined}>{value}</p>
      {sub && <p className="text-xs care-muted mt-1">{sub}</p>}
    </div>
  );
}

function Panel({ title, subtitle, children }) {
  return (
    <div className="glass-card rounded-xl p-5">
      <div className="mb-4">
        <h2 className="care-panel-title">{title}</h2>
        {subtitle && <p className="care-panel-subtitle">{subtitle}</p>}
      </div>
      {children}
    </div>
  );
}

export default function SalesDashboard({ calls }) {
  const navigate = useNavigate();
  const chart = getChartTheme(useTheme());
  const m = useMemo(() => buildSalesDashboard(calls), [calls]);

  const probData = [
    { name: "High", value: m.probability.high, color: PROB_COLORS.high },
    { name: "Medium", value: m.probability.medium, color: PROB_COLORS.medium },
    { name: "Low", value: m.probability.low, color: PROB_COLORS.low },
  ].filter((d) => d.value > 0);

  const scoreData = Object.entries(m.scoreDistribution).map(([name, value], i) => ({
    name, value, color: SCORE_COLORS[i],
  }));

  const weakData = m.weakest.map((k) => ({ name: k.name, value: k.avgPct }));

  const recent = (Array.isArray(calls) ? calls : [])
    .filter((c) => String(c.status || "").toLowerCase() === "processed")
    .slice(0, 10);

  return (
    <div className="space-y-6">
      <div className="grid grid-cols-2 lg:grid-cols-5 gap-4">
        <Card label="Sales Calls" value={m.total} />
        <Card label="Avg Sales Score" value={`${m.avgScore}/100`} accent="text-cyan-300" />
        <Card label="High Probability" value={m.probability.high} accent="text-emerald-400" sub={`${m.total ? Math.round((m.probability.high / m.total) * 100) : 0}% of calls`} />
        <Card label="Needs Review" value={`${m.reviewRate}%`} accent="text-amber-400" sub={`${m.reviewCount} calls`} />
        <Card label="Fatal Errors" value={m.fatalCount} accent="text-red-400" />
      </div>

      <div className="grid grid-cols-1 xl:grid-cols-3 gap-6">
        <Panel title="Sales Probability" subtitle="Conversion likelihood across calls">
          {probData.length ? (
            <div style={{ width: "100%", height: 240 }}>
              <ResponsiveContainer>
                <PieChart>
                  <Pie data={probData} dataKey="value" nameKey="name" cx="50%" cy="50%" innerRadius={48} outerRadius={80} paddingAngle={2} stroke={chart.pieStroke}>
                    {probData.map((d, i) => <Cell key={i} fill={d.color} />)}
                  </Pie>
                  <Tooltip />
                  <Legend verticalAlign="bottom" iconType="circle" wrapperStyle={{ fontSize: "11px", color: chart.legendColor }} />
                </PieChart>
              </ResponsiveContainer>
            </div>
          ) : <p className="care-muted text-sm">No sales calls yet.</p>}
        </Panel>

        <Panel title="Score Distribution" subtitle="Sales calls by score bucket (/100)">
          <div style={{ width: "100%", height: 240 }}>
            <ResponsiveContainer>
              <BarChart data={scoreData} margin={{ top: 12, right: 12, left: -16, bottom: 0 }}>
                <CartesianGrid stroke={chart.grid} strokeDasharray="3 3" vertical={false} />
                <XAxis dataKey="name" tick={{ fill: chart.tickBright, fontSize: 11 }} axisLine={false} tickLine={false} />
                <YAxis allowDecimals={false} tick={{ fill: chart.tick, fontSize: 11 }} axisLine={false} tickLine={false} />
                <Tooltip />
                <Bar dataKey="value" radius={[6, 6, 0, 0]}>
                  {scoreData.map((d, i) => <Cell key={i} fill={d.color} />)}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </div>
        </Panel>

        <Panel title="Weakest KPIs" subtitle="Lowest average KPI attainment — coaching focus">
          {weakData.length ? (
            <div style={{ width: "100%", height: 240 }}>
              <ResponsiveContainer>
                <BarChart data={weakData} layout="vertical" margin={{ top: 4, right: 28, left: 8, bottom: 4 }}>
                  <CartesianGrid stroke={chart.grid} strokeDasharray="3 3" horizontal={false} />
                  <XAxis type="number" domain={[0, 100]} tick={{ fill: chart.tick, fontSize: 11 }} tickFormatter={(v) => `${v}%`} axisLine={false} tickLine={false} />
                  <YAxis type="category" dataKey="name" width={130} tick={{ fill: chart.tickBright, fontSize: 11 }} axisLine={false} tickLine={false} />
                  <Tooltip />
                  <Bar dataKey="value" radius={[0, 6, 6, 0]}>
                    {weakData.map((d, i) => <Cell key={i} fill={d.value >= 60 ? "#22c55e" : d.value >= 30 ? "#f59e0b" : "#ef4444"} />)}
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            </div>
          ) : <p className="care-muted text-sm">No KPI data yet.</p>}
        </Panel>
      </div>

      <Panel title="Recent Sales Calls" subtitle="Click a row to open the Sales audit">
        {recent.length ? (
          <div className="overflow-x-auto">
            <table className="care-table w-full text-sm">
              <thead>
                <tr>
                  <th className="text-left pb-2 pr-4">File</th>
                  <th className="text-left pb-2 pr-4">Agent</th>
                  <th className="text-left pb-2 pr-4">Score</th>
                  <th className="text-left pb-2 pr-4">Probability</th>
                  <th className="text-left pb-2 pr-4">Intent</th>
                  <th className="text-left pb-2">Review</th>
                </tr>
              </thead>
              <tbody>
                {recent.map((c) => {
                  const a = c.analysis?.sales_kpi || {};
                  return (
                    <tr key={c.id} onClick={() => navigate(`/calls/${c.id}`)} className="cursor-pointer">
                      <td className="py-2 pr-4 font-mono text-xs max-w-[240px] truncate">{c.filename || c.id}</td>
                      <td className="py-2 pr-4">{formatAgentDisplayName(c)}</td>
                      <td className="py-2 pr-4 font-bold text-cyan-300">{a.total_pct ?? c.score_pct ?? "—"}/100</td>
                      <td className="py-2 pr-4 capitalize">{a.sales_probability || "—"}</td>
                      <td className="py-2 pr-4 capitalize">{a.customer_intent || "—"}</td>
                      <td className="py-2">{a.review_required ? <span className="text-amber-400">Required</span> : <span className="text-emerald-400">OK</span>}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        ) : <p className="care-muted text-sm">No processed sales calls yet.</p>}
      </Panel>
    </div>
  );
}
