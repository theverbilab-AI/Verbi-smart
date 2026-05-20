import { useEffect, useState } from "react";
import { parseTranscriptTurns, toArray } from "../utils/transcript";
import { fetchCallAudioBlob } from "../services/api";

const UI_BUILD = "2026-05-19-playback-proxy-v9";

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
  const [blobUrl, setBlobUrl] = useState(null);
  const [audioLoading, setAudioLoading] = useState(false);
  const [audioError, setAudioError] = useState(null);

  useEffect(() => {
    let revoked = null;
    setAudioError(null);
    setBlobUrl(null);

    if (!call?.id) return undefined;
    if (call.audio_available === false) {
      setAudioError("Recording not archived — re-upload after S3 is configured on the backend.");
      return undefined;
    }

    let cancelled = false;
    setAudioLoading(true);
    fetchCallAudioBlob(call.id)
      .then((url) => {
        if (!cancelled) {
          revoked = url;
          setBlobUrl(url);
        }
      })
      .catch((err) => {
        if (!cancelled) setAudioError(err.message || "Audio unavailable");
      })
      .finally(() => {
        if (!cancelled) setAudioLoading(false);
      });

    return () => {
      cancelled = true;
      if (revoked && revoked.startsWith("blob:")) URL.revokeObjectURL(revoked);
    };
  }, [call?.id, call?.audio_available]);

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
        {blobUrl ? (
          <audio
            key={blobUrl}
            controls
            preload="metadata"
            className="w-full h-10 accent-cyan-500"
            src={blobUrl}
            onError={() => setAudioError("Could not decode recording — file may be missing or corrupt on S3.")}
          >
            Your browser does not support audio playback.
          </audio>
        ) : !audioLoading ? (
          <p className="text-xs text-amber-400/90">
            {audioError || "Recording not available."}
          </p>
        ) : null}
        <p className="text-xs text-slate-500 mt-2 truncate">{call?.filename}</p>
      </div>

      {turns.length > 0 ? (
        <div className="space-y-2 mb-4 max-h-80 overflow-y-auto pr-1">
          {turns.map((turn, i) => (
            <div
              key={i}
              className={`rounded-lg px-4 py-3 border ${
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
          <p className={`text-3xl font-bold ${totalColor(complianceScore)}`}>{complianceScore}%</p>
        </div>
        <div className="bg-slate-900 rounded-lg p-4 border border-slate-700">
          <p className="text-xs text-slate-400 mb-1">Risk Level</p>
          <p
            className={`text-3xl font-bold ${
              risk === "HIGH" ? "text-red-400" : risk === "MEDIUM" ? "text-amber-400" : "text-emerald-400"
            }`}
          >
            {risk}
          </p>
        </div>
      </div>
    </div>
  );
}
