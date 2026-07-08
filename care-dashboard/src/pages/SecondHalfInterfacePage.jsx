const MODULES = [
  {
    title: "1) Sales Call Audit Queue",
    status: "Live now",
    items: ["Upload calls", "S3 ingest", "Queue + processing status", "Agent-wise tagging"],
  },
  {
    title: "2) Sales QA Scoring",
    status: "Live now",
    items: ["24-point sales rubric", "Disposition detection", "Conversion probability", "Coaching suggestions"],
  },
  {
    title: "3) Audit Dashboard",
    status: "Live now",
    items: ["Total calls", "Processed", "Avg score", "Flags + risk trends"],
  },
  {
    title: "4) Call Timeline + Detail",
    status: "Live now",
    items: ["Transcript", "Recording", "Summary", "Agent performance breakdown"],
  },
  {
    title: "5) CRM Sync (LeadSquared)",
    status: "Next",
    items: ["Disposition push", "Score push", "Conversion %", "Sync logs + retries"],
  },
  {
    title: "6) Fonada VoiceBot Runtime",
    status: "Planned",
    items: ["Fonada webhook", "Sarvam STT/TTS", "LLM conversation loop", "Audit every bot call in CARE"],
  },
];

const TODAY_ACTIONS = [
  "Freeze scope: Call BPO Sales audit only",
  "Finalize interface screens for catchup",
  "Keep collections and other verticals out of current build",
  "Prepare one-click demo flow for second-half meeting",
];

const TIMELINE = [
  { phase: "Current", focus: "Sales call audit interface", deliverable: "Meeting-ready dashboard + reports view" },
  { phase: "Next", focus: "LeadSquared sync", deliverable: "Disposition + score + conversion export" },
  { phase: "Later", focus: "Fonada VoiceBot", deliverable: "AI calling with same sales QA engine" },
];

function StatusPill({ status }) {
  const cls =
    status === "Live now"
      ? "bg-emerald-500/15 text-emerald-300 border-emerald-400/40"
      : status === "Next"
      ? "bg-amber-500/15 text-amber-300 border-amber-400/40"
      : "bg-cyan-500/15 text-cyan-300 border-cyan-400/40";
  return <span className={`text-[11px] px-2.5 py-1 rounded-full border ${cls}`}>{status}</span>;
}

export default function PlatformReadinessPage() {
  return (
    <div className="p-6 care-page space-y-6">
      <div className="glass-card rounded-xl p-5">
        <p className="text-xs uppercase tracking-wide care-muted">Platform readiness</p>
        <h1 className="care-title mt-2">Product Readiness Board</h1>
        <p className="care-subtitle">
          Current scope is only sales call audit in CARE. VoiceBot stays planned and reuses the same audit backbone.
        </p>
      </div>

      <div className="grid md:grid-cols-2 xl:grid-cols-3 gap-4">
        {MODULES.map((module) => (
          <div key={module.title} className="glass-card rounded-xl p-5 space-y-3">
            <div className="flex items-start justify-between gap-3">
              <h2 className="care-panel-title">{module.title}</h2>
              <StatusPill status={module.status} />
            </div>
            <ul className="text-sm care-text-secondary space-y-1">
              {module.items.map((item) => (
                <li key={item}>- {item}</li>
              ))}
            </ul>
          </div>
        ))}
      </div>

      <div className="grid xl:grid-cols-2 gap-6">
        <div className="glass-card rounded-xl p-5">
          <h2 className="care-panel-title">Today Before Meeting</h2>
          <ul className="mt-3 space-y-2 text-sm care-text-secondary">
            {TODAY_ACTIONS.map((action) => (
              <li key={action}>- {action}</li>
            ))}
          </ul>
        </div>

        <div className="glass-card rounded-xl p-5">
          <h2 className="care-panel-title">Execution Timeline</h2>
          <div className="mt-3 space-y-3">
            {TIMELINE.map((row) => (
              <div key={row.phase} className="care-subpanel p-3 rounded-lg">
                <p className="text-xs uppercase tracking-wide care-muted">{row.phase}</p>
                <p className="font-semibold mt-1" style={{ color: "var(--care-text-primary)" }}>{row.focus}</p>
                <p className="text-sm care-muted mt-1">{row.deliverable}</p>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}
