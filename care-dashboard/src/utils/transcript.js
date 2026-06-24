/**
 * Transcript display helpers.
 *
 * IMPORTANT: The frontend must NOT re-classify speakers. The backend
 * (speaker_attribution.py) is the single source of truth and stores verified
 * turns with confidence + reason. Re-labeling here previously caused the UI to
 * disagree with the audited transcript (labels flipping between views).
 *
 * Display order of preference:
 *   1. call.analysis.speaker_turns  (verified, with confidence/reason)
 *   2. call.transcript text         (parsed verbatim, no relabeling)
 */

const SPEAKER_LINE = /^(agent|customer)\s*:/i;

export function stripThinking(text) {
  if (!text) return "";
  let t = String(text);
  const thinkOpen = "<" + "think" + ">";
  const thinkClose = "</" + "think" + ">";
  const thinkBlock = new RegExp(`${thinkOpen}[\\s\\S]*?${thinkClose}`, "gi");
  t = t.replace(thinkBlock, "");
  t = t.replace(/<think>[\s\S]*?<\/redacted_thinking>/gi, "");
  t = t.replace(/```[\s\S]*?```/g, "");
  return t.trim();
}

const META_CUES = [
  "rules are strict", "need to be careful", "customer is the borrower",
  "numbers and dates", "must stay as they are", "should be preserved",
  "mix of hindi and english", "output only", "each line must",
];

function isMetaLine(text) {
  const t = (text || "").trim();
  if (!t || t.length < 3 || t === ".") return true;
  const low = t.toLowerCase();
  return META_CUES.some((c) => low.includes(c));
}

function normalizeSpeakerLine(line) {
  const m = line.match(/^(agent|customer)\s*:\s*(.*)$/i);
  if (!m) return line;
  const who = m[1][0].toUpperCase() + m[1].slice(1).toLowerCase();
  return `${who}: ${m[2].trim()}`;
}

/** Clean transcript text for display — keeps Agent:/Customer: lines verbatim. */
export function formatTranscript(text) {
  const cleaned = stripThinking(text);
  if (!cleaned) return "";

  const lines = [];
  for (const raw of cleaned.split(/\r?\n/)) {
    const line = raw.trim();
    if (!line) continue;
    if (SPEAKER_LINE.test(line)) {
      lines.push(normalizeSpeakerLine(line));
      continue;
    }
    const parts = line.split(/(?=(?:(?:agent|customer)\s*:))/i);
    for (const part of parts) {
      const p = part.trim();
      if (p && SPEAKER_LINE.test(p)) lines.push(normalizeSpeakerLine(p));
    }
  }

  if (lines.length) {
    const filtered = lines.filter((line) => {
      const m = line.match(/^(agent|customer)\s*:\s*(.*)$/i);
      return m && !isMetaLine(m[2]);
    });
    return filtered.join("\n");
  }

  const match = cleaned.match(/(?:^|\n)\s*(agent|customer)\s*:/i);
  if (match && match.index != null) {
    return formatTranscript(cleaned.slice(match.index));
  }

  return "";
}

/** Parse plain transcript text into turns (verbatim — no relabeling). */
export function parseTranscriptTurns(text) {
  const formatted = formatTranscript(text);
  if (!formatted) return [];
  return formatted.split(/\r?\n/).map((line) => {
    const m = line.match(/^(agent|customer)\s*:\s*(.*)$/i);
    if (!m) return { speaker: "Unknown", text: line };
    return {
      speaker: m[1].toLowerCase() === "agent" ? "Agent" : "Customer",
      text: m[2].trim(),
    };
  });
}

/**
 * Verified turns for display. Prefers the backend's canonical speaker_turns
 * (with confidence + reason) and falls back to parsing the transcript text.
 */
export function getVerifiedTurns(call) {
  const structured = call?.analysis?.speaker_turns;
  if (Array.isArray(structured) && structured.length) {
    return structured
      .filter((t) => t && (t.text || "").trim())
      .map((t) => ({
        speaker: String(t.speaker).toLowerCase() === "agent" ? "Agent" : "Customer",
        text: (t.text || "").trim(),
        confidence: typeof t.confidence === "number" ? t.confidence : null,
        reason: t.reason || "",
      }));
  }
  return parseTranscriptTurns(call?.transcript).map((t) => ({
    ...t,
    confidence: null,
    reason: "",
  }));
}

export function toArray(v) {
  if (!v) return [];
  if (Array.isArray(v)) return v.filter(Boolean);
  if (typeof v === "string") {
    try {
      const parsed = JSON.parse(v);
      if (Array.isArray(parsed)) return parsed.filter(Boolean);
    } catch (_e) {
      return v.split(/[;,|]/).map((x) => x.trim()).filter(Boolean);
    }
  }
  return [v];
}
