import { useMemo } from "react";
import { SALES_KPI_DEFS, buildSalesAgentKpis, buildSalesDashboard } from "../../utils/salesMetrics";

function cellColor(v) {
  if (v == null) return "";
  if (v >= 75) return "text-emerald-500";
  if (v >= 50) return "text-amber-500";
  return "text-rose-500";
}

export default function SalesKpiTracker({ calls }) {
  const rows = useMemo(() => buildSalesAgentKpis(calls), [calls]);
  const portfolio = useMemo(() => buildSalesDashboard(calls), [calls]);

  if (!rows.length) {
    return <p className="care-muted py-8 text-center">No processed Sales calls yet. Upload calls with Audit Type = Sales.</p>;
  }

  return (
    <div className="space-y-6">
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <Card label="Sales calls" value={portfolio.total} />
        <Card label="Avg sales score" value={`${portfolio.avgScore}/100`} accent />
        <Card label="Needs review" value={`${portfolio.reviewRate}%`} />
        <Card label="Fatal errors" value={portfolio.fatalCount} />
      </div>

      <div className="glass-card rounded-xl overflow-hidden">
        <div className="overflow-x-auto">
          <table className="care-table w-full text-sm border-collapse">
            <colgroup>
              <col style={{ width: "170px" }} />
              <col style={{ minWidth: "70px" }} />
              <col style={{ minWidth: "90px" }} />
              <col style={{ minWidth: "80px" }} />
              <col style={{ minWidth: "70px" }} />
              {SALES_KPI_DEFS.map((d) => <col key={d.id} style={{ minWidth: "64px" }} />)}
            </colgroup>
            <thead>
              <tr>
                <th rowSpan={2} className="care-sticky-col text-left py-3 px-4 text-[11px] border-r">Agent</th>
                <th colSpan={4} className="care-th-accent text-[10px] py-2 px-3 text-left border-r" style={{ borderColor: "var(--care-border)" }}>Performance</th>
                <th colSpan={SALES_KPI_DEFS.length} className="care-th-accent text-[10px] py-2 px-3 text-left">Sales KPIs (% attained)</th>
              </tr>
              <tr>
                <th className="text-right whitespace-nowrap">Calls</th>
                <th className="text-right whitespace-nowrap">Score</th>
                <th className="text-right whitespace-nowrap">Review</th>
                <th className="text-right whitespace-nowrap border-r" style={{ borderColor: "var(--care-border)" }}>Fatal</th>
                {SALES_KPI_DEFS.map((d) => (
                  <th key={d.id} title={`${d.name} (weight ${d.weight})`} className="text-center whitespace-nowrap">
                    {d.name.split(" ")[0]}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody className="tabular-nums">
              {rows.map((r) => (
                <tr key={r.agent}>
                  <td className="care-sticky-col py-3 px-4 max-w-[170px] truncate" title={r.agent}>{r.agent}</td>
                  <td className="text-right">{r.calls}</td>
                  <td className={`text-right font-semibold ${cellColor(r.avgScore)}`}>{r.avgScore}</td>
                  <td className="text-right">{r.reviewRate}%</td>
                  <td className="text-right border-r" style={{ borderColor: "var(--care-border)" }}>{r.fatal}</td>
                  {SALES_KPI_DEFS.map((d) => {
                    const v = r.kpiScores[d.id];
                    return (
                      <td key={d.id} className={`text-center whitespace-nowrap ${cellColor(v)}`}>{v}%</td>
                    );
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <div className="px-4 py-3 border-t text-xs care-muted" style={{ borderColor: "var(--care-border)", background: "var(--care-table-head)" }}>
          % attained = score ÷ max for each KPI, averaged across the agent's calls. Weights follow the KPI Sales Flow sheet (total 100).
        </div>
      </div>
    </div>
  );
}

function Card({ label, value, accent }) {
  return (
    <div className="glass-card rounded-xl p-4">
      <p className="care-chip-label">{label}</p>
      <p className={`font-bold mt-1 text-2xl ${accent ? "care-td-accent" : ""}`} style={!accent ? { color: "var(--care-text-primary)" } : undefined}>{value}</p>
    </div>
  );
}
