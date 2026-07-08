import { useState } from "react";
import { Mic, Send, RotateCcw, Sparkles, User, Bot } from "lucide-react";

const SCENARIOS = [
  { id: "outbound", label: "Outbound BPO Sales", channel: "Fonada · Outbound" },
  { id: "inbound", label: "Inbound Sales Line", channel: "Fonada · Inbound" },
  { id: "callback", label: "Callback Follow-up", channel: "Fonada · Scheduled" },
];

const SEED_TRANSCRIPT = [
  {
    role: "agent",
    text: "Namaste, main VerbiLab se bol raha hoon. Kya main aapke saath 2 minute baat kar sakta hoon?",
    meta: "Greeting · 0.8s",
  },
  {
    role: "customer",
    text: "Haan, bolo. Mujhe loan ke baare mein details chahiye.",
    meta: "STT · Hindi",
  },
  {
    role: "agent",
    text: "Bilkul. Aapka primary requirement kya hai — personal loan ya business expansion? Main aapko sirf verified product facts share karunga.",
    meta: "Need discovery · KB grounded",
  },
];

const MOCK_REPLIES = [
  {
    text: "Samajh gaya. Aapke liye ₹5–8 lakh range suitable lag rahi hai. Kya main aaj shaam 6:30 baje callback schedule kar doon?",
    slots: { product: "Personal loan", budget: "₹5–8L", intent: "medium" },
    disposition: "CALLBACK",
    latency: "1.1s",
  },
  {
    text: "Theek hai. Main aapke liye demo slot check kar raha hoon. Kya kal subah 11 baje convenient hoga?",
    slots: { product: "Personal loan", timeline: "This week", intent: "high" },
    disposition: "DEMO_SCHEDULED",
    latency: "0.9s",
  },
];

function Bubble({ role, text, meta }) {
  const isAgent = role === "agent";
  return (
    <div className={`flex gap-3 ${isAgent ? "" : "flex-row-reverse"}`}>
      <div
        className={`w-8 h-8 rounded-full flex items-center justify-center shrink-0 ${
          isAgent ? "bg-cyan-500/20 text-cyan-300" : "bg-slate-600/40 text-slate-300"
        }`}
      >
        {isAgent ? <Bot className="w-4 h-4" /> : <User className="w-4 h-4" />}
      </div>
      <div className={`max-w-[85%] ${isAgent ? "" : "text-right"}`}>
        <div
          className={`rounded-xl px-4 py-3 text-sm ${
            isAgent
              ? "care-subpanel border-cyan-500/20"
              : "bg-slate-700/40 border border-slate-600/50"
          }`}
        >
          <p className="care-text-secondary leading-relaxed">{text}</p>
        </div>
        {meta && <p className="text-[10px] care-muted mt-1 px-1">{meta}</p>}
      </div>
    </div>
  );
}

export default function VoiceBotPlaygroundPage() {
  const [scenario, setScenario] = useState(SCENARIOS[0].id);
  const [messages, setMessages] = useState(SEED_TRANSCRIPT);
  const [input, setInput] = useState("");
  const [slots, setSlots] = useState({ product: "—", budget: "—", intent: "low" });
  const [disposition, setDisposition] = useState("OPEN");
  const [lastLatency, setLastLatency] = useState("—");

  const sendMessage = () => {
    const text = input.trim();
    if (!text) return;

    const reply = MOCK_REPLIES[Math.floor(Math.random() * MOCK_REPLIES.length)];
    setMessages((prev) => [
      ...prev,
      { role: "customer", text, meta: "Simulated STT" },
      { role: "agent", text: reply.text, meta: `AI response · ${reply.latency}` },
    ]);
    setSlots(reply.slots);
    setDisposition(reply.disposition);
    setLastLatency(reply.latency);
    setInput("");
  };

  const reset = () => {
    setMessages(SEED_TRANSCRIPT);
    setSlots({ product: "—", budget: "—", intent: "low" });
    setDisposition("OPEN");
    setLastLatency("—");
    setInput("");
  };

  const activeScenario = SCENARIOS.find((s) => s.id === scenario);

  return (
    <div className="p-6 care-page space-y-6">
      <div className="glass-card rounded-xl p-5 flex flex-wrap items-start justify-between gap-4">
        <div>
          <p className="text-xs uppercase tracking-wide care-muted">Mockup Interface</p>
          <h1 className="care-title mt-2 flex items-center gap-2">
            <Sparkles className="w-6 h-6 text-cyan-400" />
            VoiceBot Playground
          </h1>
          <p className="care-subtitle">
            Conversation tester — simulate BPO sales calls before going live on Fonada.
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          {SCENARIOS.map((s) => (
            <button
              key={s.id}
              type="button"
              onClick={() => setScenario(s.id)}
              className={`text-xs px-3 py-1.5 rounded-lg border transition-colors ${
                scenario === s.id
                  ? "bg-cyan-500/15 border-cyan-500/40 text-cyan-300"
                  : "btn-secondary !py-1.5 !px-3"
              }`}
            >
              {s.label}
            </button>
          ))}
        </div>
      </div>

      <div className="grid xl:grid-cols-3 gap-6">
        <div className="xl:col-span-2 glass-card rounded-xl p-5 flex flex-col min-h-[480px]">
          <div className="flex items-center justify-between mb-4">
            <div>
              <h2 className="care-panel-title">Live Conversation</h2>
              <p className="text-xs care-muted mt-1">{activeScenario?.channel}</p>
            </div>
            <span className="badge bg-emerald-500/15 text-emerald-300">
              <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse mr-1.5 inline-block" />
              Tester active
            </span>
          </div>

          <div className="flex-1 space-y-4 overflow-y-auto pr-2 mb-4">
            {messages.map((msg, i) => (
              <Bubble key={i} role={msg.role} text={msg.text} meta={msg.meta} />
            ))}
          </div>

          <div className="flex gap-2 pt-4 border-t" style={{ borderColor: "var(--care-border)" }}>
            <input
              type="text"
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && sendMessage()}
              placeholder="Type as customer (simulated speech)…"
              className="care-input flex-1"
            />
            <button type="button" onClick={sendMessage} className="btn-primary !px-4">
              <Send className="w-4 h-4" />
            </button>
            <button type="button" className="btn-secondary !px-4" title="Simulate voice input">
              <Mic className="w-4 h-4" />
            </button>
          </div>
        </div>

        <div className="space-y-4">
          <div className="glass-card rounded-xl p-5">
            <h2 className="care-panel-title">Captured Slots</h2>
            <div className="mt-3 space-y-2">
              {Object.entries(slots).map(([key, val]) => (
                <div key={key} className="care-subpanel flex justify-between text-sm">
                  <span className="care-muted capitalize">{key}</span>
                  <span className="font-medium" style={{ color: "var(--care-text-primary)" }}>{val}</span>
                </div>
              ))}
            </div>
          </div>

          <div className="glass-card rounded-xl p-5">
            <h2 className="care-panel-title">Session Metrics</h2>
            <div className="mt-3 grid grid-cols-2 gap-3">
              <div className="care-chip">
                <p className="care-chip-label">Disposition</p>
                <p className="care-chip-value text-cyan-400">{disposition}</p>
              </div>
              <div className="care-chip">
                <p className="care-chip-label">Turn latency</p>
                <p className="care-chip-value">{lastLatency}</p>
              </div>
              <div className="care-chip col-span-2">
                <p className="care-chip-label">Post-call</p>
                <p className="text-xs care-text-secondary mt-1">→ CARE sales audit · LeadSquared sync</p>
              </div>
            </div>
          </div>

          <button type="button" onClick={reset} className="btn-secondary w-full justify-center">
            <RotateCcw className="w-4 h-4" />
            Reset conversation
          </button>
        </div>
      </div>
    </div>
  );
}
