import { useEffect, useMemo, useState } from "react";
import { getCalls } from "../services/api";
import {
  PARAMS,
  buildAgentKpis,
  buildCustomerKpis,
  buildPortfolioKpis,
} from "../utils/kpiMetrics";

const TABS = [
  { id: "agent", label: "Agent (§6.1)" },
  { id: "customer", label: "Customer / Loan (§6.2)" },
  { id: "portfolio", label: "Portfolio (§6.3)" },
];

export default function KpiTrackerPage() {
  const [calls, setCalls] = useState([]);
  const [loading, setLoading] = useState(true);
  const [tab, setTab] = useState("agent");
  const [filters, setFilters] = useState({ from: "", to: "", agent_id: "", disposition: "" });

  useEffect(() => {
    let mounted = true;
    (async () => {
      setLoading(true);
      try {
        const params = { limit: 500 };
        if (filters.from) params.from = filters.from;
        if (filters.to) params.to = filters.to;
        if (filters.agent_id) params.agent_id = filters.agent_id;
        if (filters.disposition) params.disposition = filters.disposition;
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

  const agentRows = useMemo(() => buildAgentKpis(calls), [calls]);
  const customerRows = useMemo(() => buildCustomerKpis(calls), [calls]);
  const portfolio = useMemo(() => buildPortfolioKpis(calls), [calls]);

  return (
    <div className="p-6 text-slate-100 space-y-6">
      <div>
        <h1 className="text-2xl font-bold">KPI Tracker</h1>
        <p className="text-xs text-slate-500 mt-1">
          Verbicare PRD §6.1–6.3 · Excludes: PTP Conversion/Broken, DPD, Best Call Time, Audit Coverage,
          Collection Effectiveness, Promise Reliability
        </p>
      </div>

      <FilterBar filters={filters} setFilters={setFilters} />

      <div className="flex gap-2 border-b border-slate-700 pb-1">
        {TABS.map((t) => (
          <button
            key={t.id}
            type="button"
            onClick={() => setTab(t.id)}
            className={`px-4 py-2 text-sm rounded-t-lg transition-colors ${
              tab === t.id
                ? "bg-cyan-950/50 text-cyan-300 border border-cyan-800/50 border-b-transparent"
                : "text-slate-400 hover:text-slate-200"
            }`}
          >
            {t.label}
          </button>
        ))}
      </div>

      {loading ? (
        <p className="text-slate-400 animate-pulse">Loading KPIs…</p>
      ) : (
        <>
          {tab === "agent" && <AgentTab rows={agentRows} />}
          {tab === "customer" && <CustomerTab rows={customerRows} />}
          {tab === "portfolio" && <PortfolioTab data={portfolio} />}
        </>
      )}
    </div>
  );
}

function FilterBar({ filters, setFilters }) {
  return (
    <div className="flex flex-wrap gap-3 glass-card rounded-xl p-4">
      <input
        type="date"
        value={filters.from}
        onChange={(e) => setFilters((f) => ({ ...f, from: e.target.value }))}
        className="bg-slate-800 rounded-lg px-3 py-2 text-sm border border-slate-600"
      />
      <input
        type="date"
        value={filters.to}
        onChange={(e) => setFilters((f) => ({ ...f, to: e.target.value }))}
        className="bg-slate-800 rounded-lg px-3 py-2 text-sm border border-slate-600"
      />
      <input
        type="text"
        placeholder="Agent ID"
        value={filters.agent_id}
        onChange={(e) => setFilters((f) => ({ ...f, agent_id: e.target.value }))}
        className="bg-slate-800 rounded-lg px-3 py-2 text-sm border border-slate-600"
      />
      <select
        value={filters.disposition}
        onChange={(e) => setFilters((f) => ({ ...f, disposition: e.target.value }))}
        className="bg-slate-800 rounded-lg px-3 py-2 text-sm border border-slate-600"
      >
        <option value="">All dispositions</option>
        <option value="PTP">PTP</option>
        <option value="CALLBACK">Callback</option>
        <option value="WRONG_NUMBER">Wrong number</option>
        <option value="OTHER">Other</option>
      </select>
    </div>
  );
}

function AgentTab({ rows }) {
  if (!rows.length) {
    return <Empty message="No processed calls for agent KPIs." />;
  }
  return (
    <div className="overflow-x-auto glass-card rounded-xl p-4">
      <table className="w-full text-sm">
        <thead>
          <tr className="text-slate-500 text-xs uppercase border-b border-slate-700">
            <th className="text-left py-2 pr-3">Agent</th>
            <th className="text-left py-2 pr-3">Calls audited</th>
            <th className="text-left py-2 pr-3">Overall quality</th>
            <th className="text-left py-2 pr-3">Critical fail %</th>
            <th className="text-left py-2 pr-3">Resolution %</th>
            <th className="text-left py-2 pr-3">Objection (A4)</th>
            <th className="text-left py-2 pr-3">Tone (1–5)</th>
            <th className="text-left py-2 pr-3">Language %</th>
            <th className="text-left py-2 pr-3">Trend 7d / 30d</th>
            <th className="text-left py-2 pr-3">Flags</th>
            {PARAMS.map((p) => (
              <th key={p.key} className="text-left py-2 pr-2 whitespace-nowrap">
                {p.label}
                {p.critical ? " *" : ""}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.agent_id} className="border-b border-slate-700/40 hover:bg-slate-800/30">
              <td className="py-2 pr-3 font-medium">{r.agent_id}</td>
              <td className="py-2 pr-3">{r.calls_audited}</td>
              <td className="py-2 pr-3 font-bold text-cyan-300">{r.overall_quality_score}%</td>
              <td className="py-2 pr-3 text-amber-400">{r.critical_fail_rate}%</td>
              <td className="py-2 pr-3">{r.call_resolution_rate}%</td>
              <td className="py-2 pr-3">{r.objection_handling_score ?? "—"}%</td>
              <td className="py-2 pr-3">{r.tone_score}</td>
              <td className="py-2 pr-3">
                {r.language_adherence_pct}% ({r.language_primary})
              </td>
              <td className="py-2 pr-3 text-xs">
                {r.trend_score_7d} / {r.trend_score_30d}
                <span className="text-slate-500 ml-1">({r.trend_delta})</span>
              </td>
              <td className="py-2 pr-3">{r.compliance_flags_count}</td>
              {PARAMS.map((p) => (
                <td key={p.key} className="py-2 pr-2 text-slate-300">
                  {r.parameter_scores[p.key] ?? "—"}/{p.max}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
      <p className="text-xs text-slate-600 mt-3">
        AHT, talk ratio, dead air, overtalk, empathy, coaching sessions require audio analytics (not in v1).
      </p>
    </div>
  );
}

function CustomerTab({ rows }) {
  const [expanded, setExpanded] = useState(null);
  if (!rows.length) return <Empty message="No loan/customer data yet." />;

  return (
    <div className="space-y-3">
      {rows.map((r) => (
        <div key={r.loan_id} className="glass-card rounded-xl p-4">
          <button
            type="button"
            className="w-full text-left flex flex-wrap items-center justify-between gap-2"
            onClick={() => setExpanded(expanded === r.loan_id ? null : r.loan_id)}
          >
            <span className="font-semibold text-cyan-300">Loan {r.loan_id}</span>
            <span className="text-xs text-slate-500">{r.total_calls_received} calls</span>
          </button>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mt-3 text-sm">
            <KpiChip label="Risk score" value={`${r.risk_score}/100`} />
            <KpiChip label="Last contacted" value={r.last_contacted} />
            <KpiChip label="Last outcome" value={r.last_outcome} />
            <KpiChip label="Objection handling" value={`${r.objection_handling_score}%`} />
            <KpiChip label="Dispute" value={r.dispute_flag} warn={r.dispute_flag === "Yes"} />
            <KpiChip label="Escalation" value={r.escalation_flag} warn={r.escalation_flag === "Yes"} />
            <KpiChip label="Aggression / abuse" value={r.aggression_abuse_flag} warn={r.aggression_abuse_flag === "Yes"} />
            <KpiChip label="Language" value={r.language_preference} />
            <KpiChip label="Outstanding (LMS)" value={r.outstanding_loan_amount} />
          </div>
          {expanded === r.loan_id && (
            <div className="mt-4 grid md:grid-cols-2 gap-4 text-xs">
              <div>
                <p className="text-slate-500 uppercase mb-2">PTP history</p>
                {r.ptp_history.length ? (
                  <ul className="space-y-1 text-slate-300">
                    {r.ptp_history.map((p, i) => (
                      <li key={i}>
                        {p.amount ?? "—"} · {p.date ?? "—"} · {p.mode ?? "—"}
                      </li>
                    ))}
                  </ul>
                ) : (
                  <p className="text-slate-600">No PTPs recorded</p>
                )}
              </div>
              <div>
                <p className="text-slate-500 uppercase mb-2">Sentiment history</p>
                <ul className="space-y-1 text-slate-300 max-h-32 overflow-y-auto">
                  {r.call_sentiment_history.map((s, i) => (
                    <li key={i}>
                      {s.sentiment} · {s.disposition} · {Math.round(s.score_pct)}%
                    </li>
                  ))}
                </ul>
              </div>
            </div>
          )}
        </div>
      ))}
    </div>
  );
}

function PortfolioTab({ data }) {
  return (
    <div className="space-y-6">
      <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-4">
        <PortfolioCard label="Total calls processed" value={data.total_calls_processed} />
        <PortfolioCard label="Average quality score" value={`${data.average_quality_score}%`} />
        <PortfolioCard label="PTP rate" value={`${data.ptp_rate}%`} />
        <PortfolioCard label="Compliance breach rate" value={`${data.compliance_breach_rate}%`} />
        <PortfolioCard label="Portfolio risk score" value={`${data.risk_score_portfolio}/100`} />
        <PortfolioCard label="Last contacted (any)" value={data.last_contacted_any} small />
      </div>

      <div className="glass-card rounded-xl p-4">
        <h3 className="text-sm font-semibold text-slate-300 mb-3">Top performing agents</h3>
        {data.top_performing_agents.length ? (
          <table className="w-full text-sm">
            <thead>
              <tr className="text-slate-500 text-xs uppercase border-b border-slate-700">
                <th className="text-left py-2">Agent</th>
                <th className="text-left py-2">Calls</th>
                <th className="text-left py-2">Avg score</th>
                <th className="text-left py-2">Critical fail %</th>
              </tr>
            </thead>
            <tbody>
              {data.top_performing_agents.map((a) => (
                <tr key={a.agent_id} className="border-b border-slate-700/40">
                  <td className="py-2 font-medium">{a.agent_id}</td>
                  <td className="py-2">{a.calls_audited}</td>
                  <td className="py-2 text-cyan-300 font-bold">{a.overall_quality_score}%</td>
                  <td className="py-2">{a.critical_fail_rate}%</td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : (
          <p className="text-slate-500 text-sm">No agents yet.</p>
        )}
      </div>
    </div>
  );
}

function KpiChip({ label, value, warn }) {
  return (
    <div className={`rounded-lg px-3 py-2 border ${warn ? "border-amber-700/50 bg-amber-950/20" : "border-slate-700 bg-slate-900/50"}`}>
      <p className="text-xs text-slate-500">{label}</p>
      <p className="font-medium truncate">{value}</p>
    </div>
  );
}

function PortfolioCard({ label, value, small }) {
  return (
    <div className="glass-card rounded-xl p-4">
      <p className="text-xs text-slate-500">{label}</p>
      <p className={`font-bold text-cyan-300 mt-1 ${small ? "text-sm" : "text-2xl"}`}>{value}</p>
    </div>
  );
}

function Empty({ message }) {
  return <p className="text-slate-500 py-8 text-center">{message}</p>;
}
