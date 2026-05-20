import { useEffect, useMemo, useState } from "react";
import { getCalls } from "../services/api";

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

export default function KpiTrackerPage() {
  const [calls, setCalls] = useState([]);
  const [loading, setLoading] = useState(true);
  const [filters, setFilters] = useState({ from: "", to: "", agent_id: "" });

  useEffect(() => {
    let mounted = true;
    (async () => {
      setLoading(true);
      try {
        const params = { limit: 500, status: "processed" };
        if (filters.from) params.from = filters.from;
        if (filters.to) params.to = filters.to;
        if (filters.agent_id) params.agent_id = filters.agent_id;
        const data = await getCalls(params);
        if (mounted) setCalls(Array.isArray(data) ? data : data.calls ?? []);
      } catch (e) {
        console.error(e);
      } finally {
        if (mounted) setLoading(false);
      }
    })();
    return () => { mounted = false; };
  }, [filters]);

  const rows = useMemo(() => buildAgentKpis(calls), [calls]);

  return (
    <div className="p-6 text-white space-y-6">
      <div>
        <h1 className="text-2xl font-bold">KPI Tracker</h1>
        <p className="text-xs text-gray-500 mt-1">Agent-level quality metrics · Verbicare PRD §6.1</p>
      </div>

      <div className="flex flex-wrap gap-3 bg-gray-800/60 rounded-xl p-4 border border-gray-700">
        <input type="date" value={filters.from} onChange={(e) => setFilters((f) => ({ ...f, from: e.target.value }))}
          className="bg-gray-700 rounded-lg px-3 py-2 text-sm border border-gray-600" />
        <input type="date" value={filters.to} onChange={(e) => setFilters((f) => ({ ...f, to: e.target.value }))}
          className="bg-gray-700 rounded-lg px-3 py-2 text-sm border border-gray-600" />
        <input type="text" placeholder="Agent ID" value={filters.agent_id}
          onChange={(e) => setFilters((f) => ({ ...f, agent_id: e.target.value }))}
          className="bg-gray-700 rounded-lg px-3 py-2 text-sm border border-gray-600" />
      </div>

      {loading ? <p className="text-gray-400 animate-pulse">Loading KPIs…</p> : (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-gray-500 text-xs uppercase border-b border-gray-700">
                <th className="text-left py-2 pr-4">Agent</th>
                <th className="text-left py-2 pr-4">Calls</th>
                <th className="text-left py-2 pr-4">Avg Score</th>
                <th className="text-left py-2 pr-4">PTP %</th>
                <th className="text-left py-2 pr-4">Critical Fail %</th>
                <th className="text-left py-2 pr-4">Flags</th>
                {PARAMS.map((p) => (
                  <th key={p.key} className="text-left py-2 pr-2 whitespace-nowrap">
                    {p.label}{p.critical ? " *" : ""}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.length === 0 ? (
                <tr><td colSpan={6 + PARAMS.length} className="py-6 text-gray-500">No processed calls for filters.</td></tr>
              ) : rows.map((r) => (
                <tr key={r.agent_id} className="border-b border-gray-700/50 hover:bg-gray-800/40">
                  <td className="py-2 pr-4 font-medium">{r.agent_id}</td>
                  <td className="py-2 pr-4">{r.calls_audited}</td>
                  <td className="py-2 pr-4 font-bold text-cyan-300">{r.overall_quality_score}%</td>
                  <td className="py-2 pr-4">{r.ptp_conversion_rate}%</td>
                  <td className="py-2 pr-4 text-amber-400">{r.critical_fail_rate}%</td>
                  <td className="py-2 pr-4">{r.compliance_flags_count}</td>
                  {PARAMS.map((p) => (
                    <td key={p.key} className="py-2 pr-2 text-gray-300">
                      {r.parameter_scores[p.key] ?? "—"}/{p.max}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

function buildAgentKpis(calls) {
  const list = (calls || []).filter((c) => c.status === "processed");
  const byAgent = new Map();

  for (const call of list) {
    const agent = call.agent_id || call.agent_name || "Unknown";
    const row = byAgent.get(agent) || {
      agent_id: agent,
      calls_audited: 0,
      score_sum: 0,
      ptp: 0,
      critical_fail: 0,
      flags: 0,
      param_sums: Object.fromEntries(PARAMS.map((p) => [p.key, 0])),
      param_counts: Object.fromEntries(PARAMS.map((p) => [p.key, 0])),
    };
    row.calls_audited += 1;
    row.score_sum += Number(call.score_pct ?? call.score ?? 0);
    if (call.ptp_detected) row.ptp += 1;
    if (call.critical_fail) row.critical_fail += 1;
    row.flags += Array.isArray(call.compliance_flags) ? call.compliance_flags.length : 0;

    const breakdown = call.scores_breakdown || call.scores || {};
    for (const p of PARAMS) {
      const v = breakdown[p.key];
      if (v != null && v !== "") {
        row.param_sums[p.key] += Number(v);
        row.param_counts[p.key] += 1;
      }
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
    return {
      agent_id: r.agent_id,
      calls_audited: r.calls_audited,
      overall_quality_score: Math.round(r.score_sum / n),
      ptp_conversion_rate: Math.round((r.ptp / n) * 100),
      critical_fail_rate: Math.round((r.critical_fail / n) * 100),
      compliance_flags_count: r.flags,
      parameter_scores,
    };
  }).sort((a, b) => b.overall_quality_score - a.overall_quality_score);
}
