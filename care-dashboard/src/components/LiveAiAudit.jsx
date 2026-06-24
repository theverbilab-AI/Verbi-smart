import { useEffect, useRef, useState } from "react";
import { parseTranscriptTurns, toArray } from "../utils/transcript";
import { getCallAudioUrl } from "../services/api";

const UI_BUILD = "2026-06-24-audio-stream-v13";
const PLAYBACK_RATES = [0.75, 1, 1.25, 1.5, 2];

function getOpeningAudit(call) {
  return call?.analysis?.opening_audit || call?.opening_audit || null;
}

/**
 * Single transcript block — audio + dialogue + AI insights only.
 */
export default function LiveAiAudit({
  call,
  complianceScore,
  risk,
  totalColor,
}) {
  const turns = parseTranscriptTurns(call?.transcript);
  const detections = toArray(call?.ai_detection).filter((d) => d && d !== "NONE");
  const [audioLoading, setAudioLoading] = useState(false);
  const [audioError, setAudioError] = useState(null);
  const [playbackRate, setPlaybackRate] = useState(1);
  const [activeTurn, setActiveTurn] = useState(0);
  const audioRef = useRef(null);
  const turnRefs = useRef([]);
  const opening = getOpeningAudit(call);

  const audioSrc =
    call?.id && call?.audio_available !== false ? getCallAudioUrl(call.id) : null;

  useEffect(() => {
    setActiveTurn(0);
    turnRefs.current = [];
  }, [call?.id, turns.length]);

  useEffect(() => {
    setAudioError(null);
    setAudioLoading(Boolean(audioSrc));
    if (call?.audio_available === false) {
      setAudioError("Recording not archived — re-upload after S3 is configured on the backend.");
      setAudioLoading(false);
    }
  }, [call?.id, call?.audio_available, audioSrc]);

  useEffect(() => {
    const audio = audioRef.current;
    if (!audio || turns.length === 0) return undefined;

    const syncTurn = () => {
      const duration = audio.duration;
      if (!duration || !Number.isFinite(duration) || duration <= 0) return;
      const idx = Math.min(
        turns.length - 1,
        Math.max(0, Math.floor((audio.currentTime / duration) * turns.length))
      );
      setActiveTurn((prev) => {
        if (prev !== idx) {
          turnRefs.current[idx]?.scrollIntoView({ block: "nearest", behavior: "smooth" });
        }
        return idx;
      });
    };

    audio.addEventListener("timeupdate", syncTurn);
    audio.addEventListener("seeked", syncTurn);
    return () => {
      audio.removeEventListener("timeupdate", syncTurn);
      audio.removeEventListener("seeked", syncTurn);
    };
  }, [audioSrc, turns.length]);

  return (
    <div
      className="glass-card rounded-xl p-5 mb-4 glow-cyan"
      data-care-ui={UI_BUILD}
    >
      <div className="flex items-center justify-between mb-4">
        <h2 className="text-sm font-bold tracking-widest text-cyan-400 uppercase">Live AI Audit</h2>
        <span className="text-[10px] text-slate-600 font-mono">{UI_BUILD}</span>
      </div>

      <div className="bg-slate-900/80 rounded-lg p-4 mb-4 border border-slate-700/60">
        <p className="text-xs text-slate-500 mb-2">Call Recording</p>
        {audioLoading && (
          <p className="text-xs text-cyan-400/80 mb-2 animate-pulse">Loading recording…</p>
        )}
        {audioSrc ? (
          <>
            <audio
              ref={audioRef}
              key={audioSrc}
              controls
              preload="metadata"
              className="w-full h-10 accent-cyan-500"
              src={audioSrc}
              onLoadStart={() => setAudioLoading(true)}
              onCanPlay={() => setAudioLoading(false)}
              onLoadedMetadata={(e) => { e.currentTarget.playbackRate = playbackRate; }}
              onError={() => {
                setAudioLoading(false);
                setAudioError("Could not load recording — sign out/in and refresh, or ask admin to redeploy backend.");
              }}
            >
              Your browser does not support audio playback.
            </audio>
            <div className="flex items-center gap-2 mt-2">
              <span className="text-xs text-slate-500">Speed</span>
              {PLAYBACK_RATES.map((r) => (
                <button
                  key={r}
                  type="button"
                  onClick={() => {
                    setPlaybackRate(r);
                    if (audioRef.current) audioRef.current.playbackRate = r;
                  }}
                  className={`text-xs px-2 py-0.5 rounded border ${
                    playbackRate === r
                      ? "border-cyan-500 text-cyan-300 bg-cyan-950/40"
                      : "border-slate-600 text-slate-400 hover:border-slate-500"
                  }`}
                >
                  {r}x
                </button>
              ))}
            </div>
          </>
        ) : !audioLoading ? (
          <p className="text-xs text-amber-400/90">
            {audioError || "Recording not available."}
          </p>
        ) : null}
        <p className="text-xs text-slate-500 mt-2 truncate">{call?.filename}</p>
      </div>

      {opening?.is_collections !== false && (
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 mb-4">
          {[
            { key: "disclaimer_given", label: "Disclaimer" },
            { key: "agent_intro_done", label: "Agent intro" },
            { key: "customer_name_used", label: "Customer name" },
            { key: "rpc_confirmed", label: "RPC confirmed" },
          ].map(({ key, label }) => (
            <div
              key={key}
              className={`rounded-lg px-3 py-2 text-center border text-xs border-slate-600 bg-slate-800/50 ${
                opening[key] ? "text-cyan-200" : "text-slate-500"
              }`}
            >
              <p className="font-semibold">{opening[key] ? "Done" : "Pending"}</p>
              <p className="text-slate-400 mt-0.5">{label}</p>
            </div>
          ))}
        </div>
      )}

      {turns.length > 0 ? (
        <div className="space-y-2 mb-4 max-h-80 overflow-y-auto pr-1">
          {turns.map((turn, i) => (
            <div
              key={i}
              ref={(el) => { turnRefs.current[i] = el; }}
              onClick={() => {
                const audio = audioRef.current;
                if (!audio?.duration || !Number.isFinite(audio.duration)) return;
                audio.currentTime = (i / turns.length) * audio.duration;
                setActiveTurn(i);
              }}
              className={`rounded-lg px-4 py-3 border cursor-pointer transition-all ${
                i === activeTurn
                  ? "ring-2 ring-cyan-400/80 shadow-lg shadow-cyan-900/30"
                  : ""
              } ${
                turn.speaker === "Agent"
                  ? "bg-cyan-950/30 border-cyan-800/40"
                  : "bg-slate-800/70 border-slate-700/40"
              }`}
            >
              <p
                className={`text-xs font-semibold mb-1 ${
                  turn.speaker === "Agent" ? "text-cyan-400" : "text-slate-400"
                }`}
              >
                {turn.speaker}
              </p>
              <p className="text-sm text-slate-200 leading-relaxed">{turn.text}</p>
            </div>
          ))}
        </div>
      ) : (
        <p className="text-sm text-slate-500 mb-4">Transcript not available.</p>
      )}

      {detections.length > 0 && (
        <div className="bg-slate-900/90 rounded-lg px-4 py-3 mb-3 border border-slate-700/50">
          <p className="text-xs text-slate-400 mb-1">AI Detection</p>
          <p className="text-sm font-semibold text-cyan-300">{detections.join(" · ")}</p>
        </div>
      )}

      {call?.ai_suggestion && (
        <div className="bg-slate-900/90 rounded-lg px-4 py-3 mb-4 border border-slate-700/50">
          <p className="text-xs text-slate-400 mb-1">AI Suggestion</p>
          <p className="text-sm text-slate-200">{call.ai_suggestion}</p>
        </div>
      )}

      <div className="grid grid-cols-2 gap-3">
        <div className="bg-slate-900 rounded-lg p-4 border border-slate-700">
          <p className="text-xs text-slate-400 mb-1">Compliance Score</p>
          <p className="text-3xl font-bold text-cyan-300">{complianceScore}%</p>
        </div>
        <div className="bg-slate-900 rounded-lg p-4 border border-slate-700">
          <p className="text-xs text-slate-400 mb-1">Risk Level</p>
          <p className="text-3xl font-bold text-slate-200">{risk}</p>
        </div>
      </div>
    </div>
  );
}
