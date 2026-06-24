import { useEffect, useState } from "react";
import { getCrmUsage } from "../services/api";

export default function CrmUsagePage() {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    (async () => {
      try {
        const res = await getCrmUsage();
        setData(res);
      } catch (e) {
        setError(e.message || "Could not load CRM usage");
      } finally {
        setLoading(false);
      }
    })();
  }, []);

  const logs = data?.recent_logs ?? [];
  const providers = data?.by_provider ?? [];

  return (
    <div className="p-6 text-white space-y-6 max-w-6xl">
      <div>
        <h1 className="text-2xl font-bold">CRM Usage Metrics</h1>
        <p className="text-sm text-slate-400 mt-1">LeadSquared API sync attempts and estimated usage for cost tracking.</p>
      </div>

      {error && (
        <div className="bg-red-900/40 border border-red-700 text-red-300 rounded-lg px-4 py-3 text-sm">{error}</div>
      )}

      {loading ? (
        <p className="text-slate-400 animate-pulse">Loading…</p>
      ) : (
        <>
          <div className="grid md:grid-cols-3 gap-4">
            <div className="glass-card rounded-xl p-4">
              <p className="text-xs text-slate-500 uppercase">Estimated usage</p>
              <p className="text-2xl font-bold text-cyan-400">{data?.estimated_usage_count ?? 0}</p>
            </div>
            {providers.map((p) => (
              <div key={p.crm_provider} className="glass-card rounded-xl p-4">
                <p className="text-xs text-slate-500 uppercase">{p.crm_provider}</p>
                <p className="text-lg font-semibold">{p.success_count}/{p.total_calls} success</p>
                <p className="text-xs text-slate-400">avg {p.avg_duration_ms} ms</p>
              </div>
            ))}
          </div>

          <div className="glass-card rounded-xl overflow-hidden">
            <h2 className="font-semibold px-5 py-3 border-b border-slate-700">Recent API calls</h2>
            <table className="w-full text-sm">
              <thead>
                <tr className="text-slate-500 text-xs uppercase border-b border-slate-700">
                  <th className="text-left p-3">Time</th>
                  <th className="text-left p-3">Provider</th>
                  <th className="text-left p-3">Endpoint</th>
                  <th className="text-left p-3">Lead / Call</th>
                  <th className="text-left p-3">Status</th>
                </tr>
              </thead>
              <tbody>
                {logs.length === 0 ? (
                  <tr><td colSpan={5} className="p-5 text-slate-500">No CRM API calls logged yet.</td></tr>
                ) : logs.map((row) => (
                  <tr key={row.id} className="border-b border-slate-800/60">
                    <td className="p-3 text-xs">{row.created_at || "—"}</td>
                    <td className="p-3">{row.crm_provider}</td>
                    <td className="p-3 font-mono text-xs truncate max-w-[200px]">{row.endpoint}</td>
                    <td className="p-3 text-xs">{row.lead_id || "—"} / {row.call_id || "—"}</td>
                    <td className="p-3">
                      <span className={row.success ? "text-emerald-400" : "text-red-400"}>
                        {row.status_code ?? "—"} {row.success ? "OK" : "FAIL"}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
    </div>
  );
}
