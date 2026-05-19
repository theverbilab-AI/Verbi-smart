import { useEffect, useState } from "react";
import { parseTranscriptTurns, toArray } from "../utils/transcript";
import { fetchCallAudioBlob } from "../services/api";

const UI_BUILD = "2026-05-19-audio-upload-v5";

/**
 * Single transcript block — audio + dialogue + AI insights only.
 */
export default function LiveAiAudit({
  call,
  audioSrc,
  complianceScore,
  risk,
  totalColor,
}) {
  const turns = parseTranscriptTurns(call?.transcript);
  const detections = toArray(call?.ai_detection).filter((d) => d && d !== "NONE");
  const [blobUrl, setBlobUrl] = useState(null);
  const [audioError, setAudioError] = useState(null);

  useEffect(() => {
    let revoked = null;
    setAudioError(null);
    setBlobUrl(null);

    const direct = call?.audio_playback_url;
    if (direct && direct.startsWith("http")) {
      setBlobUrl(direct);
      return undefined;
    }

    if (!call?.id) return undefined;

    let cancelled = false;
    fetchCallAudioBlob(call.id)
      .then((url) => {
        if (!cancelled) {
          revoked = url;
          setBlobUrl(url);
        }
      })
      .catch((err) => {
        if (!cancelled) setAudioError(err.message || "Audio unavailable");
      });

    return () => {
      cancelled = true;
      if (revoked && revoked.startsWith("blob:")) URL.revokeObjectURL(revoked);
    };
  }, [call?.id, call?.audio_playback_url]);

  const playerSrc = blobUrl || audioSrc;
  const externalAudio =
    playerSrc?.startsWith("http") &&
    !playerSrc.startsWith(window.location.origin);

  return (
    <div
      className="bg-gray-900 border border-gray-700 rounded-xl p-5 mb-4"
      data-care-ui={UI_BUILD}
    >
      <div className="flex items-center justify-between mb-4">
        <h2 className="text-sm font-bold tracking-widest text-lime-400 uppercase">Live AI Audit</h2>
        <span className="text-[10px] text-gray-600 font-mono">{UI_BUILD}</span>
      </div>

      <div className="bg-gray-800 rounded-lg p-4 mb-4 border border-gray-700/60">
        <p className="text-xs text-gray-500 mb-2">Call Recording</p>
        {playerSrc ? (
          <audio
            key={playerSrc}
            controls
            preload="metadata"
            {...(externalAudio ? { crossOrigin: "anonymous" } : {})}
            className="w-full h-10"
            src={playerSrc}
            onError={() => setAudioError("Could not load recording — re-upload or check S3/AWS on Railway")}
          >
            Your browser does not support audio playback.
          </audio>
        ) : (
          <p className="text-xs text-amber-400/90">
            {audioError || "Recording not available (enable S3 on backend for playback after deploy)."}
          </p>
        )}
        <p className="text-xs text-gray-500 mt-2 truncate">{call?.filename}</p>
      </div>

      {turns.length > 0 ? (
        <div className="space-y-2 mb-4 max-h-80 overflow-y-auto pr-1">
          {turns.map((turn, i) => (
            <div
              key={i}
              className={`rounded-lg px-4 py-3 border ${
                turn.speaker === "Agent"
                  ? "bg-gray-800/90 border-gray-600/50"
                  : "bg-gray-800/70 border-gray-700/40"
              }`}
            >
              <p className="text-xs font-semibold text-gray-400 mb-1">{turn.speaker}</p>
              <p className="text-sm text-gray-200 leading-relaxed">{turn.text}</p>
            </div>
          ))}
        </div>
      ) : (
        <p className="text-sm text-gray-500 mb-4">Transcript not available.</p>
      )}

      {detections.length > 0 && (
        <div className="bg-gray-800/90 rounded-lg px-4 py-3 mb-3 border border-gray-700/50">
          <p className="text-xs text-gray-400 mb-1">AI Detection</p>
          <p className="text-sm font-semibold text-lime-400">{detections.join(" · ")}</p>
        </div>
      )}

      {call?.ai_suggestion && (
        <div className="bg-gray-800/90 rounded-lg px-4 py-3 mb-4 border border-gray-700/50">
          <p className="text-xs text-gray-400 mb-1">AI Suggestion</p>
          <p className="text-sm text-gray-200">{call.ai_suggestion}</p>
        </div>
      )}

      <div className="grid grid-cols-2 gap-3">
        <div className="bg-gray-800 rounded-lg p-4 border border-gray-700">
          <p className="text-xs text-gray-400 mb-1">Compliance Score</p>
          <p className={`text-3xl font-bold ${totalColor(complianceScore)}`}>{complianceScore}%</p>
        </div>
        <div className="bg-gray-800 rounded-lg p-4 border border-gray-700">
          <p className="text-xs text-gray-400 mb-1">Risk Level</p>
          <p
            className={`text-3xl font-bold ${
              risk === "HIGH" ? "text-red-400" : risk === "MEDIUM" ? "text-yellow-400" : "text-green-400"
            }`}
          >
            {risk}
          </p>
        </div>
      </div>
    </div>
  );
}
