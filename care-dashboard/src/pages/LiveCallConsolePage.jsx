const LIVE_CALLS = [
  { id: "LC-1034", lead: "Ravi K", stage: "Need Discovery", intent: "Medium", latency: "1.2s", sentiment: "Neutral" },
  { id: "LC-1037", lead: "Sneha P", stage: "Objection Handling", intent: "High", latency: "1.5s", sentiment: "Positive" },
  { id: "LC-1038", lead: "Arun M", stage: "Closing", intent: "High", latency: "0.9s", sentiment: "Positive" },
];

const TIMELINE = [
  "Agent greeted and confirmed language preference.",
  "Lead asked for pricing and repayment flexibility.",
  "AI suggested concise objection response from knowledge base.",
  "Next action proposed: callback slot today 6:30 PM.",
];

export default function LiveCallConsolePage() {
  return (
    <div className="p-6 care-page space-y-6">
      <div className="glass-card rounded-xl p-5">
        <p className="text-xs uppercase tracking-wide care-muted">Mockup Interface</p>
        <h1 className="care-title mt-2">Live Call Console</h1>
        <p className="care-subtitle">Supervisor cockpit for monitoring active AI-assisted sales calls in real time.</p>
      </div>

      <div className="grid xl:grid-cols-3 gap-6">
        <div className="xl:col-span-2 glass-card rounded-xl p-5">
          <div className="flex items-center justify-between">
            <h2 className="care-panel-title">Active Sessions</h2>
            <span className="badge bg-emerald-500/15 text-emerald-300">{LIVE_CALLS.length} live</span>
          </div>
          <div className="mt-4 overflow-x-auto">
            <table className="care-table w-full text-sm">
              <thead>
                <tr>
                  <th className="text-left">Call ID</th>
                  <th className="text-left">Lead</th>
                  <th className="text-left">Stage</th>
                  <th className="text-left">Intent</th>
                  <th className="text-left">Latency</th>
                  <th className="text-left">Sentiment</th>
                </tr>
              </thead>
              <tbody>
                {LIVE_CALLS.map((row) => (
                  <tr key={row.id}>
                    <td className="font-mono">{row.id}</td>
                    <td>{row.lead}</td>
                    <td>{row.stage}</td>
                    <td>{row.intent}</td>
                    <td>{row.latency}</td>
                    <td>{row.sentiment}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>

        <div className="glass-card rounded-xl p-5">
          <h2 className="care-panel-title">Current Call Timeline</h2>
          <div className="mt-4 space-y-3">
            {TIMELINE.map((item, idx) => (
              <div key={item} className="care-subpanel">
                <p className="text-xs care-muted">T+{idx + 1} min</p>
                <p className="text-sm mt-1 care-text-secondary">{item}</p>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}
