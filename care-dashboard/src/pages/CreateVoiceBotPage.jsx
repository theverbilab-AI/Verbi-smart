const STEPS = [
  { id: "01", title: "Campaign Basics", desc: "Name, channel, calling window, concurrency, retry rules." },
  { id: "02", title: "Audience & Lead Source", desc: "CSV upload, CRM segment, dedupe, priority tags." },
  { id: "03", title: "Voice & Language", desc: "Sarvam voice preset, language strategy, fallback voice." },
  { id: "04", title: "AI Goal & Success", desc: "Qualification goal, exit criteria, KPI targets." },
];

const PRESETS = [
  { name: "BPO Outbound Sales", tags: ["High volume", "Qualification-first", "Callback optimized"] },
  { name: "Inbound Sales Helpline", tags: ["Intent capture", "Warm transfer", "Compliance-safe"] },
  { name: "Demo Booking Sprint", tags: ["Short calls", "Calendar-first", "Conversion focus"] },
];

export default function CreateVoiceBotPage() {
  return (
    <div className="p-6 care-page space-y-6">
      <div className="glass-card rounded-xl p-5">
        <p className="text-xs uppercase tracking-wide care-muted">Mockup Interface</p>
        <h1 className="care-title mt-2">Create VoiceBot</h1>
        <p className="care-subtitle">UI-only wizard for configuring a new enterprise sales voice agent.</p>
      </div>

      <div className="grid xl:grid-cols-3 gap-6">
        <div className="xl:col-span-2 glass-card rounded-xl p-5">
          <h2 className="care-panel-title">Configuration Flow</h2>
          <div className="mt-4 grid md:grid-cols-2 gap-4">
            {STEPS.map((step) => (
              <div key={step.id} className="care-subpanel">
                <div className="flex items-center justify-between">
                  <p className="text-xs font-semibold tracking-wide care-muted">Step {step.id}</p>
                  <span className="badge bg-cyan-500/15 text-cyan-300">Draft</span>
                </div>
                <p className="mt-2 font-semibold" style={{ color: "var(--care-text-primary)" }}>{step.title}</p>
                <p className="text-sm care-muted mt-1">{step.desc}</p>
              </div>
            ))}
          </div>
        </div>

        <div className="glass-card rounded-xl p-5">
          <h2 className="care-panel-title">Quick Presets</h2>
          <div className="mt-4 space-y-3">
            {PRESETS.map((preset) => (
              <div key={preset.name} className="care-subpanel">
                <p className="font-semibold" style={{ color: "var(--care-text-primary)" }}>{preset.name}</p>
                <div className="mt-2 flex flex-wrap gap-2">
                  {preset.tags.map((tag) => (
                    <span key={tag} className="badge bg-emerald-500/15 text-emerald-300">{tag}</span>
                  ))}
                </div>
              </div>
            ))}
          </div>
          <button type="button" className="btn-primary mt-4 w-full justify-center">Create Draft Bot</button>
        </div>
      </div>
    </div>
  );
}
