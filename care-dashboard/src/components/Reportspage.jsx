import { useState, useEffect, useCallback } from "react";
import { useNavigate } from "react-router-dom";
import { getCalls, getAgentKPIs } from "../services/api";
import { PRODUCT_NAME } from "../config/branding.js";

// ── Helpers ───────────────────────────────────────────────────────────────────
function downloadCSV(rows, filename) {
  if (!rows.length) return;
  const headers = Object.keys(rows[0]);
  const csv = [
    headers.join(","),
    ...rows.map(r => headers.map(h => `"${(r[h] ?? "").toString().replace(/"/g, '""')}"`).join(","))
  ].join("\n");
  const blob = new Blob([csv], { type: "text/csv" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a"); a.href = url; a.download = filename; a.click();
  URL.revokeObjectURL(url);
}

function fmt(dt) {
  if (!dt) return "—";
  return new Date(dt).toLocaleString("en-IN", { dateStyle: "short", timeStyle: "short" });
}

function scoreColor(pct) {
  if (pct >= 70) return "text-green-400";
  if (pct >= 40) return "text-yellow-400";
  return "text-red-400";
}

const TABS = ["Loan Report", "Agent Report", "KPI Dashboard"];

// ── Main Component ────────────────────────────────────────────────────────────
export default function ReportsPage() {
  const navigate = useNavigate();
  const [tab, setTab] = useState(0);
  const [calls, setCalls] = useState([]);
  const [agents, setAgents] = useState([]);
  const [loading, setLoading] = useState(true);
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo]   = useState("");
  const [search, setSearch]   = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [callsData, agentsData] = await Promise.all([getCalls(), getAgentKPIs()]);
      setCalls(Array.isArray(callsData) ? callsData : callsData.calls ?? []);
      setAgents(agentsData.agents ?? []);
    } catch (e) { console.error(e); }
    finally { setLoading(false); }
  }, []);

  useEffect(() => { load(); }, [load]);

  // ── Filter calls by date + search ─────────────────────────────────────────
  const filtered = calls.filter(c => {
    const d = new Date(c.uploaded_at);
    const from = dateFrom ? new Date(dateFrom) : null;
    const to   = dateTo   ? new Date(dateTo + "T23:59:59") : null;
    if (from && d < from) return false;
    if (to   && d > to)   return false;
    if (search) {
      const q = search.toLowerCase();
      return (
        c.filename?.toLowerCase().includes(q) ||
        c.agent_id?.toLowerCase().includes(q) ||
        c.loan_id?.toLowerCase().includes(q)
      );
    }
    return true;
  });

  const processed = filtered.filter(c => c.status === "processed");

  // ── Loan-level report rows ─────────────────────────────────────────────────
  const loanRows = processed.map(c => ({
    "Call ID":        c.id,
    "File":           c.filename,
    "Agent ID":       c.agent_id ?? "—",
    "Loan ID":        c.loan_id  ?? "—",
    "Date":           fmt(c.uploaded_at),
    "Score /20":      c.score ?? "—",
    "Score %":        c.score_pct ?? "—",
    "PTP Secured":    c.ptp_detected ? "Yes" : "No",
    "PTP Amount":     c.ptp_amount ?? "—",
    "PTP Date":       c.ptp_date   ?? "—",
    "PTP Mode":       c.ptp_mode   ?? "—",
    "Flags":          (c.compliance_flags ?? []).join("; ") || "None",
    "A1 Opening":     c.scores_breakdown?.A1_opening        ?? "—",
    "A2 Case Know":   c.scores_breakdown?.A2_case_knowledge ?? "—",
    "A3 Probing":     c.scores_breakdown?.A3_probing        ?? "—",
    "A4 Negotiation": c.scores_breakdown?.A4_negotiation    ?? "—",
    "A5 PTP":         c.scores_breakdown?.A5_commitment_ptp ?? "—",
    "A6 Closing":     c.scores_breakdown?.A6_closing        ?? "—",
    "A7 Professionalism": c.scores_breakdown?.A7_professionalism ?? "—",
    "A8 Call Handling":   c.scores_breakdown?.A8_call_handling   ?? "—",
    "A9 Troubleshoot":    c.scores_breakdown?.A9_troubleshooting ?? "—",
    "Summary":        c.summary ?? "—",
    "Coaching Tip":   c.coaching_tip ?? "—",
  }));

  // ── Agent-level report rows ────────────────────────────────────────────────
  const agentMap = {};
  processed.forEach(c => {
    const aid = c.agent_id || "Unknown";
    if (!agentMap[aid]) agentMap[aid] = { calls: 0, totalScore: 0, ptps: 0, flags: 0, scores: {} };
    agentMap[aid].calls++;
    agentMap[aid].totalScore += c.score ?? 0;
    if (c.ptp_detected) agentMap[aid].ptps++;
    agentMap[aid].flags += (c.compliance_flags ?? []).length;
    // Accumulate per-parameter
    Object.entries(c.scores_breakdown ?? {}).forEach(([k, v]) => {
      agentMap[aid].scores[k] = (agentMap[aid].scores[k] ?? 0) + (v ?? 0);
    });
  });

  const agentRows = Object.entries(agentMap).map(([aid, d]) => ({
    "Agent ID":       aid,
    "Total Calls":    d.calls,
    "Avg Score /20":  (d.totalScore / d.calls).toFixed(1),
    "Avg Score %":    Math.round((d.totalScore / d.calls / 20) * 100),
    "PTP Rate %":     Math.round((d.ptps / d.calls) * 100),
    "PTPs Secured":   d.ptps,
    "Flag Count":     d.flags,
    "Avg A1":  (d.scores.A1_opening        / d.calls).toFixed(1),
    "Avg A2":  (d.scores.A2_case_knowledge / d.calls).toFixed(1),
    "Avg A3":  (d.scores.A3_probing        / d.calls).toFixed(1),
    "Avg A4":  (d.scores.A4_negotiation    / d.calls).toFixed(1),
    "Avg A5":  (d.scores.A5_commitment_ptp / d.calls).toFixed(1),
    "Avg A6":  (d.scores.A6_closing        / d.calls).toFixed(1),
    "Avg A7":  (d.scores.A7_professionalism/ d.calls).toFixed(1),
  }));

  // ── KPI Summary ────────────────────────────────────────────────────────────
  const totalCalls   = processed.length;
  const avgScore     = totalCalls ? (processed.reduce((s,c) => s + (c.score??0), 0) / totalCalls).toFixed(1) : 0;
  const ptpRate      = totalCalls ? Math.round((processed.filter(c=>c.ptp_detected).length/totalCalls)*100) : 0;
  const flagRate     = totalCalls ? Math.round((processed.filter(c=>c.compliance_flags?.length).length/totalCalls)*100) : 0;
  const threatCount  = processed.filter(c=>c.compliance_flags?.includes("THREAT")).length;
  const abuseCount   = processed.filter(c=>c.compliance_flags?.includes("ABUSE")).length;

  return (
    <div className="p-6 text-white">
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-2xl font-bold">Reports</h1>
        <button onClick={load} className="text-xs text-cyan-400 hover:text-cyan-300">↻ Refresh</button>
      </div>

      {/* Date + Search Filters */}
      <div className="bg-gray-800 rounded-xl p-4 mb-5 flex flex-wrap gap-3 items-end">
        <div>
          <p className="text-xs text-gray-400 mb-1">From</p>
          <input type="date" value={dateFrom} onChange={e=>setDateFrom(e.target.value)}
            className="bg-gray-700 rounded-lg px-3 py-2 text-sm border border-gray-600 outline-none focus:border-cyan-500" />
        </div>
        <div>
          <p className="text-xs text-gray-400 mb-1">To</p>
          <input type="date" value={dateTo} onChange={e=>setDateTo(e.target.value)}
            className="bg-gray-700 rounded-lg px-3 py-2 text-sm border border-gray-600 outline-none focus:border-cyan-500" />
        </div>
        <div className="flex-1 min-w-[200px]">
          <p className="text-xs text-gray-400 mb-1">Search</p>
          <input type="text" placeholder="Agent ID, Loan ID, filename..." value={search}
            onChange={e=>setSearch(e.target.value)}
            className="w-full bg-gray-700 rounded-lg px-3 py-2 text-sm border border-gray-600 outline-none focus:border-cyan-500" />
        </div>
        <button onClick={()=>{setDateFrom("");setDateTo("");setSearch("");}}
          className="text-xs text-gray-400 hover:text-white px-3 py-2">Clear</button>
        <div className="text-xs text-gray-400 py-2">{processed.length} processed calls</div>
      </div>

      {/* Tabs */}
      <div className="flex gap-1 mb-5 bg-gray-800 rounded-xl p-1 w-fit">
        {TABS.map((t,i) => (
          <button key={t} onClick={()=>setTab(i)}
            className={`px-4 py-2 rounded-lg text-sm font-medium transition-colors ${tab===i ? "bg-cyan-600 text-white" : "text-gray-400 hover:text-white"}`}>
            {t}
          </button>
        ))}
      </div>

      {loading ? (
        <p className="text-gray-400 text-sm animate-pulse">Loading...</p>
      ) : (
        <>
          {/* ── TAB 0: Loan Report ── */}
          {tab === 0 && (
            <div>
              <div className="flex justify-between items-center mb-3">
                <h2 className="font-semibold text-gray-300">Loan-Level Report ({loanRows.length} calls)</h2>
                <button onClick={()=>downloadCSV(loanRows, `${PRODUCT_NAME}_Loan_Report_${new Date().toISOString().slice(0,10)}.csv`)}
                  className="bg-cyan-600 hover:bg-cyan-500 text-white text-xs px-4 py-2 rounded-lg font-medium transition-colors">
                  ⬇ Download CSV
                </button>
              </div>
              <div className="bg-gray-800 rounded-xl overflow-x-auto">
                <table className="w-full text-sm min-w-[900px]">
                  <thead>
                    <tr className="border-b border-gray-700 text-gray-400 text-xs uppercase">
                      {["File","Agent","Loan ID","Date","Score","PTP","Flags","A3","A4","A5","A7"].map(h=>(
                        <th key={h} className="text-left px-4 py-3">{h}</th>
                      ))}
                      <th className="px-4 py-3"></th>
                    </tr>
                  </thead>
                  <tbody>
                    {loanRows.length === 0 ? (
                      <tr><td colSpan={12} className="px-4 py-8 text-center text-gray-500">No processed calls in selected range</td></tr>
                    ) : loanRows.map((r,i) => {
                      const call = processed[i];
                      const pct  = call?.score_pct ?? 0;
                      return (
                        <tr key={i} className="border-b border-gray-700/50 hover:bg-gray-700/30 cursor-pointer transition-colors"
                          onClick={()=>navigate(`/calls/${call?.id}`)}>
                          <td className="px-4 py-3 font-mono text-xs text-gray-300 max-w-[160px] truncate">{r["File"]}</td>
                          <td className="px-4 py-3">{r["Agent ID"]}</td>
                          <td className="px-4 py-3">{r["Loan ID"]}</td>
                          <td className="px-4 py-3 text-xs text-gray-400">{r["Date"]}</td>
                          <td className={`px-4 py-3 font-bold ${scoreColor(pct)}`}>{r["Score /20"]}/20</td>
                          <td className="px-4 py-3">
                            <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${call?.ptp_detected ? "bg-green-900/50 text-green-400":"bg-red-900/50 text-red-400"}`}>
                              {call?.ptp_detected ? "✓ PTP":"✗ None"}
                            </span>
                          </td>
                          <td className="px-4 py-3">
                            {(call?.compliance_flags??[]).map(f=>(
                              <span key={f} className="text-xs bg-red-900/40 text-red-300 px-1.5 py-0.5 rounded mr-1">{f}</span>
                            ))}
                          </td>
                          <td className="px-4 py-3 text-center">{r["A3 Probing"]}/3</td>
                          <td className="px-4 py-3 text-center">{r["A4 Negotiation"]}/3</td>
                          <td className="px-4 py-3 text-center">{r["A5 PTP"]}/3</td>
                          <td className="px-4 py-3 text-center">{r["A7 Professionalism"]}/3</td>
                          <td className="px-4 py-3 text-cyan-400 text-xs">View →</td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            </div>
          )}

          {/* ── TAB 1: Agent Report ── */}
          {tab === 1 && (
            <div>
              <div className="flex justify-between items-center mb-3">
                <h2 className="font-semibold text-gray-300">Agent-Level Report ({agentRows.length} agents)</h2>
                <button onClick={()=>downloadCSV(agentRows, `${PRODUCT_NAME}_Agent_Report_${new Date().toISOString().slice(0,10)}.csv`)}
                  className="bg-cyan-600 hover:bg-cyan-500 text-white text-xs px-4 py-2 rounded-lg font-medium transition-colors">
                  ⬇ Download CSV
                </button>
              </div>
              <div className="bg-gray-800 rounded-xl overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b border-gray-700 text-gray-400 text-xs uppercase">
                      {["Agent ID","Calls","Avg Score","Score %","PTP Rate","PTPs","Flags","A3 Probe","A4 Nego","A5 PTP","A7 Prof"].map(h=>(
                        <th key={h} className="text-left px-4 py-3">{h}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {agentRows.length === 0 ? (
                      <tr><td colSpan={11} className="px-4 py-8 text-center text-gray-500">No agent data available</td></tr>
                    ) : agentRows.sort((a,b)=>b["Avg Score %"]-a["Avg Score %"]).map((r,i)=>(
                      <tr key={i} className="border-b border-gray-700/50 hover:bg-gray-700/30">
                        <td className="px-4 py-3 font-semibold">{r["Agent ID"]}</td>
                        <td className="px-4 py-3">{r["Total Calls"]}</td>
                        <td className={`px-4 py-3 font-bold ${scoreColor(r["Avg Score %"])}`}>{r["Avg Score /20"]}/20</td>
                        <td className={`px-4 py-3 font-bold ${scoreColor(r["Avg Score %"])}`}>{r["Avg Score %"]}%</td>
                        <td className="px-4 py-3">{r["PTP Rate %"]}%</td>
                        <td className="px-4 py-3">{r["PTPs Secured"]}</td>
                        <td className="px-4 py-3">{r["Flag Count"] > 0 ? <span className="text-red-400">{r["Flag Count"]}</span> : <span className="text-green-400">0</span>}</td>
                        <td className="px-4 py-3 text-center">{r["Avg A3"]}/3</td>
                        <td className="px-4 py-3 text-center">{r["Avg A4"]}/3</td>
                        <td className="px-4 py-3 text-center">{r["Avg A5"]}/3</td>
                        <td className="px-4 py-3 text-center">{r["Avg A7"]}/3</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}

          {/* ── TAB 2: KPI Dashboard ── */}
          {tab === 2 && (
            <div>
              <div className="flex justify-between items-center mb-4">
                <h2 className="font-semibold text-gray-300">KPI Dashboard</h2>
                <button onClick={()=>downloadCSV([{
                  "Total Calls": totalCalls, "Avg Score /20": avgScore,
                  "PTP Rate %": ptpRate, "Flag Rate %": flagRate,
                  "Threat Count": threatCount, "Abuse Count": abuseCount,
                }], `${PRODUCT_NAME}_KPI_${new Date().toISOString().slice(0,10)}.csv`)}
                  className="bg-cyan-600 hover:bg-cyan-500 text-white text-xs px-4 py-2 rounded-lg font-medium">
                  ⬇ Download KPI CSV
                </button>
              </div>
              <div className="grid grid-cols-2 md:grid-cols-3 gap-4 mb-6">
                {[
                  { label: "Total Calls Processed", value: totalCalls, color: "text-white" },
                  { label: "Avg Score", value: `${avgScore}/20`, color: scoreColor((avgScore/20)*100) },
                  { label: "PTP Rate", value: `${ptpRate}%`, color: ptpRate >= 50 ? "text-green-400":"text-yellow-400" },
                  { label: "Compliance Flag Rate", value: `${flagRate}%`, color: flagRate > 20 ? "text-red-400":"text-green-400" },
                  { label: "Threat Flags", value: threatCount, color: threatCount > 0 ? "text-red-400":"text-green-400" },
                  { label: "Abuse Flags", value: abuseCount, color: abuseCount > 0 ? "text-red-400":"text-green-400" },
                ].map(({label,value,color})=>(
                  <div key={label} className="bg-gray-800 rounded-xl p-5">
                    <p className="text-xs text-gray-400 uppercase mb-1">{label}</p>
                    <p className={`text-3xl font-bold ${color}`}>{value}</p>
                  </div>
                ))}
              </div>

              {/* Parameter averages */}
              <div className="bg-gray-800 rounded-xl p-5">
                <h3 className="text-sm font-semibold text-gray-400 uppercase mb-4">Avg Score by Parameter (all agents)</h3>
                {[
                  {key:"A1_opening",label:"A1 Opening",max:2},
                  {key:"A2_case_knowledge",label:"A2 Case Knowledge",max:2},
                  {key:"A3_probing",label:"A3 Probing",max:3,critical:true},
                  {key:"A4_negotiation",label:"A4 Negotiation",max:3,critical:true},
                  {key:"A5_commitment_ptp",label:"A5 Commitment/PTP",max:3,critical:true},
                  {key:"A6_closing",label:"A6 Closing",max:2},
                  {key:"A7_professionalism",label:"A7 Professionalism",max:3,critical:true},
                  {key:"A8_call_handling",label:"A8 Call Handling",max:1},
                  {key:"A9_troubleshooting",label:"A9 Troubleshooting",max:1},
                ].map(({key,label,max,critical})=>{
                  const avg = totalCalls ? (processed.reduce((s,c)=>s+(c.scores_breakdown?.[key]??0),0)/totalCalls) : 0;
                  const pct = (avg/max)*100;
                  return (
                    <div key={key} className="mb-3">
                      <div className="flex justify-between text-sm mb-1">
                        <span className="text-gray-300 flex items-center gap-2">
                          {label}
                          {critical && <span className="text-xs px-1.5 py-0.5 rounded bg-red-900/40 text-red-400 font-semibold">CRITICAL</span>}
                        </span>
                        <span className="font-medium">{avg.toFixed(1)} / {max}</span>
                      </div>
                      <div className="h-2 bg-gray-700 rounded-full overflow-hidden">
                        <div className={`h-full rounded-full ${pct>=75?"bg-green-500":pct>=50?"bg-yellow-500":"bg-red-500"}`}
                          style={{width:`${pct}%`}} />
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>
          )}
        </>
      )}
    </div>
  );
}