const FLOW_NODES = [
  { name: "Greeting", type: "Start", color: "bg-cyan-500/15 text-cyan-300" },
  { name: "Language Detect", type: "Logic", color: "bg-indigo-500/15 text-indigo-300" },
  { name: "Need Discovery", type: "Prompt", color: "bg-emerald-500/15 text-emerald-300" },
  { name: "Objection Handler", type: "Prompt", color: "bg-amber-500/15 text-amber-300" },
  { name: "Close / Callback", type: "Outcome", color: "bg-fuchsia-500/15 text-fuchsia-300" },
];

const PROMPT_BLOCKS = [
  "System role and business objective",
  "Compliance and do-not-say rules",
  "Knowledge base grounding policy",
  "Objection playbook",
  "Disposition mapping",
];

export default function PromptFlowBuilderPage() {
  return (
    <div className="p-6 care-page space-y-6">
      <div className="glass-card rounded-xl p-5">
        <p className="text-xs uppercase tracking-wide care-muted">Mockup Interface</p>
        <h1 className="care-title mt-2">Prompt & Flow Builder</h1>
        <p className="care-subtitle">SuperBot-inspired builder: visual flow plus enterprise prompt controls in one workspace.</p>
      </div>

      <div className="grid xl:grid-cols-5 gap-6">
        <div className="xl:col-span-2 glass-card rounded-xl p-5">
          <h2 className="care-panel-title">Prompt Studio</h2>
          <div className="mt-4 space-y-3">
            {PROMPT_BLOCKS.map((block) => (
              <div key={block} className="care-subpanel flex items-center justify-between">
                <p className="text-sm care-text-secondary">{block}</p>
                <span className="badge bg-cyan-500/15 text-cyan-300">Configured</span>
              </div>
            ))}
          </div>
          <button type="button" className="btn-secondary mt-4 w-full justify-center">Save Prompt Version v12</button>
        </div>

        <div className="xl:col-span-3 glass-card rounded-xl p-5">
          <div className="flex items-center justify-between">
            <h2 className="care-panel-title">Flow Canvas</h2>
            <span className="badge bg-emerald-500/15 text-emerald-300">Preview Mode</span>
          </div>
          <div className="mt-4 grid md:grid-cols-2 gap-3">
            {FLOW_NODES.map((node) => (
              <div key={node.name} className="care-subpanel">
                <div className="flex items-center justify-between">
                  <p className="font-semibold" style={{ color: "var(--care-text-primary)" }}>{node.name}</p>
                  <span className={`badge ${node.color}`}>{node.type}</span>
                </div>
                <p className="text-xs care-muted mt-2">Drag-connect in visual mode or bind to prompt policy.</p>
              </div>
            ))}
          </div>
          <div className="mt-4 flex flex-wrap gap-3">
            <button type="button" className="btn-primary">Deploy to Staging</button>
            <button type="button" className="btn-secondary">Publish to Campaign</button>
          </div>
        </div>
      </div>
    </div>
  );
}
