import { useEffect, useMemo, useState } from "react";
import { getCalls, callsFromResponse } from "../services/api";
import {
  PARAMS,
  buildAgentKpis,
  buildCustomerKpis,
  buildPortfolioKpis,
  formatAgentDisplayName,
} from "../utils/kpiMetrics";

const TABS = [
  { id: "agent", label: "Agent" },
  { id: "customer", label: "Customer / Loan" },
  { id: "portfolio", label: "Portfolio" },
];

export default function KpiTrackerPage() {
  const [calls, setCalls] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [tab, setTab] = useState("agent");
  const [filters, setFilters] = useState({ from: "", to: "", agent_name: "", disposition: "" });

  useEffect(() => {
    let mounted = true;
    (async () => {
      setLoading(true);
      setError(null);
      try {
        const params = { limit: 500 };
        if (filters.from) params.from = filters.from;
        if (filters.to) params.to = filters.to;
        if (filters.disposition) params.disposition = filters.disposition;
        const data = await getCalls(params);
        if (mounted) setCalls(callsFromResponse(data));
      } catch (e) {
        console.error(e);
        if (mounted) {
          setError(e.message || "Could not load calls for KPIs.");
          setCalls([]);
        }
      } finally {
        if (mounted) setLoading(false);
      }
    })();
    return () => { mounted = false; };
  }, [filters.from, filters.to, filters.disposition]);

  const filteredCalls = useMemo(() => {
    const q = filters.agent_name.trim().toLowerCase();
    if (!q) return calls;
    return calls.filter((c) => formatAgentDisplayName(c).toLowerCase().includes(q));
  }, [calls, filters.agent_name]);

  const agentRows = useMemo(() => buildAgentKpis(filteredCalls), [filteredCalls]);
  const customerRows = useMemo(() => buildCustomerKpis(filteredCalls), [filteredCalls]);
  const portfolio = useMemo(() => buildPortfolioKpis(filteredCalls), [filteredCalls]);

  return (
    <div className="p-6 care-page space-y-6">
      <div>
        <h1 className="care-title">KPI Tracker</h1>
        <p className="care-subtitle">
          Verbicare PRD KPIs · Excludes: PTP Conversion/Broken, DPD, Best Call Time, Audit Coverage,
          Collection Effectiveness, Promise Reliability
        </p>
      </div>

      <FilterBar filters={filters} setFilters={setFilters} />

      {error && (
        <div className="bg-red-900/40 border border-red-700 text-red-300 rounded-lg px-4 py-3 text-sm">
          ⚠ {error}
        </div>
      )}

      <div className="care-tabs">
        {TABS.map((t) => (
          <button
            key={t.id}
            type="button"
            onClick={() => setTab(t.id)}
            className={`care-tab ${tab === t.id ? "care-tab-active" : ""}`}
          >
            {t.label}
          </button>
        ))}
      </div>

      {loading ? (
        <p className="care-muted animate-pulse">Loading KPIs…</p>
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
  const fieldClass = "care-input";
  return (
    <div className="care-filter-bar glass-card">
      <input
        type="date"
        value={filters.from}
        onChange={(e) => setFilters((f) => ({ ...f, from: e.target.value }))}
        className={fieldClass}
      />
      <input
        type="date"
        value={filters.to}
        onChange={(e) => setFilters((f) => ({ ...f, to: e.target.value }))}
        className={fieldClass}
      />
      <input
        type="text"
        placeholder="Agent Name"
        value={filters.agent_name}
        onChange={(e) => setFilters((f) => ({ ...f, agent_name: e.target.value }))}
        className={fieldClass}
      />
      <select
        value={filters.disposition}
        onChange={(e) => setFilters((f) => ({ ...f, disposition: e.target.value }))}
        className={fieldClass}
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

  const PERF_COLS = [
    { label: "Calls", key: "calls_audited", align: "right" },
    { label: "Quality", key: "overall_quality_score", align: "right", suffix: "%", accent: true },
    { label: "Critical Fail", key: "critical_fail_rate", align: "right", suffix: "%", warn: true },
    { label: "Resolution", key: "call_resolution_rate", align: "right", suffix: "%" },
    { label: "Objection (A4)", key: "objection_handling_score", align: "right", suffix: "%" },
    { label: "Tone /5", key: "tone_score", align: "right" },
    { label: "Lang", key: "language_primary", align: "left" },
    { label: "Flags", key: "compliance_flags_count", align: "right" },
  ];

  return (
    <div className="glass-card rounded-xl overflow-hidden">
      <div className="overflow-x-auto">
        <table className="care-table w-full text-sm border-collapse">
          <colgroup>
            <col style={{ width: "180px" }} />
            {PERF_COLS.map((c) => (
              <col key={c.key} style={{ minWidth: "90px" }} />
            ))}
            <col style={{ minWidth: "110px" }} />
            {PARAMS.map((p) => (
              <col key={p.key} style={{ minWidth: "72px" }} />
            ))}
          </colgroup>

          <thead>
            <tr>
              <th
                rowSpan={2}
                className="care-sticky-col text-left py-3 px-4 text-[11px] border-r"
              >
                Agent
              </th>
              <th
                colSpan={PERF_COLS.length + 1}
                className="care-th-accent text-[10px] py-2 px-3 text-left border-r"
                style={{ borderColor: "var(--care-border)" }}
              >
                Performance
              </th>
              <th
                colSpan={PARAMS.length}
                className="care-th-accent text-[10px] py-2 px-3 text-left"
              >
                Parameter Scores (A1–A9)
              </th>
            </tr>
            <tr>
              {PERF_COLS.map((c) => (
                <th
                  key={c.key}
                  className={`whitespace-nowrap ${
                    c.align === "right" ? "text-right" : "text-left"
                  }`}
                >
                  {c.label}
                </th>
              ))}
              <th className="text-right whitespace-nowrap border-r" style={{ borderColor: "var(--care-border)" }}>
                Trend 7d / 30d
              </th>
              {PARAMS.map((p) => (
                <th
                  key={p.key}
                  title={p.label + (p.critical ? " (critical)" : "")}
                  className={`text-center whitespace-nowrap ${
                    p.critical ? "text-amber-500" : ""
                  }`}
                >
                  {p.key.split("_")[0]}
                  {p.critical && <span className="ml-0.5">*</span>}
                </th>
              ))}
            </tr>
          </thead>

          <tbody className="tabular-nums">
            {rows.map((r) => (
              <tr key={r.agent_id}>
                <td className="care-sticky-col py-3 px-4 max-w-[180px]" title={r.agent_id}>
                  {r.agent_id}
                </td>
                {PERF_COLS.map((c) => {
                  const v = r[c.key];
                  let display =
                    v == null || v === ""
                      ? "—"
                      : c.suffix
                      ? `${v}${c.suffix}`
                      : v;
                  if (c.key === "language_primary") {
                    display = (
                      <span className="inline-flex items-baseline gap-1">
                        <span>{r.language_primary}</span>
                        <span className="text-[10px] care-muted">{r.language_adherence_pct}%</span>
                      </span>
                    );
                  }
                  return (
                    <td
                      key={c.key}
                      className={`whitespace-nowrap ${
                        c.align === "right" ? "text-right" : "text-left"
                      } ${c.accent ? "care-td-accent" : c.warn ? "care-td-warn" : ""}`}
                    >
                      {display}
                    </td>
                  );
                })}
                <td className="text-right whitespace-nowrap border-r" style={{ borderColor: "var(--care-border)" }}>
                  <span className="font-medium">{r.trend_score_7d}</span>
                  <span className="care-muted mx-1">/</span>
                  <span>{r.trend_score_30d}</span>
                  <span
                    className={`ml-2 text-[10px] font-medium ${
                      String(r.trend_delta).startsWith("+")
                        ? "text-emerald-600"
                        : String(r.trend_delta).startsWith("-")
                        ? "text-rose-600"
                        : "care-muted"
                    }`}
                  >
                    {r.trend_delta}
                  </span>
                </td>
                {PARAMS.map((p) => {
                  const val = r.parameter_scores[p.key];
                  return (
                    <td key={p.key} className="text-center whitespace-nowrap">
                      <span className="font-medium">{val ?? "—"}</span>
                      <span className="care-muted">/{p.max}</span>
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="px-4 py-3 border-t flex flex-wrap items-center justify-between gap-2 text-xs care-muted" style={{ borderColor: "var(--care-border)", background: "var(--care-table-head)" }}>
        <span>
          <span className="text-amber-500">*</span> Critical parameter — score 0 triggers Critical Fail
        </span>
        <span>AHT, talk ratio, dead air, overtalk, empathy require audio analytics (v2)</span>
      </div>
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
            <span className="font-semibold care-td-accent">Loan {r.loan_id}</span>
            <span className="text-xs care-muted">{r.total_calls_received} calls</span>
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
                <p className="care-muted uppercase mb-2 text-xs">PTP history</p>
                {r.ptp_history.length ? (
                  <ul className="space-y-1 care-text-secondary">
                    {r.ptp_history.map((p, i) => (
                      <li key={i}>
                        {p.amount ?? "—"} · {p.date ?? "—"} · {p.mode ?? "—"}
                      </li>
                    ))}
                  </ul>
                ) : (
                  <p className="care-muted">No PTPs recorded</p>
                )}
              </div>
              <div>
                <p className="care-muted uppercase mb-2 text-xs">Sentiment history</p>
                <ul className="space-y-1 care-text-secondary max-h-32 overflow-y-auto">
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
        <h3 className="text-sm font-semibold care-text-secondary mb-3">Top performing agents</h3>
        {data.top_performing_agents.length ? (
          <table className="care-table w-full text-sm">
            <thead>
              <tr>
                <th className="text-left py-2">Agent</th>
                <th className="text-left py-2">Calls</th>
                <th className="text-left py-2">Avg score</th>
                <th className="text-left py-2">Critical fail %</th>
              </tr>
            </thead>
            <tbody>
              {data.top_performing_agents.map((a) => (
                <tr key={a.agent_id}>
                  <td className="py-2 font-medium">{a.agent_id}</td>
                  <td className="py-2">{a.calls_audited}</td>
                  <td className="py-2 care-td-accent">{a.overall_quality_score}%</td>
                  <td className="py-2">{a.critical_fail_rate}%</td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : (
          <p className="care-muted text-sm">No agents yet.</p>
        )}
      </div>
    </div>
  );
}

function KpiChip({ label, value, warn }) {
  return (
    <div className={`care-chip ${warn ? "border-amber-500/60" : ""}`}>
      <p className="care-chip-label">{label}</p>
      <p className="care-chip-value">{value}</p>
    </div>
  );
}

function PortfolioCard({ label, value, small }) {
  return (
    <div className="glass-card rounded-xl p-4">
      <p className="care-chip-label">{label}</p>
      <p className={`care-td-accent font-bold mt-1 ${small ? "text-sm" : "text-2xl"}`}>{value}</p>
    </div>
  );
}

function Empty({ message }) {
  return <p className="care-muted py-8 text-center">{message}</p>;
}
