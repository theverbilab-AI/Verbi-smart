/** Strip LLM reasoning and keep only Agent:/Customer: dialogue for display. */

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

  if (lines.length) return lines.join("\n");

  const match = cleaned.match(/(?:^|\n)\s*(agent|customer)\s*:/i);
  if (match && match.index != null) {
    return formatTranscript(cleaned.slice(match.index));
  }

  return "";
}

function normalizeSpeakerLine(line) {
  const m = line.match(/^(agent|customer)\s*:\s*(.*)$/i);
  if (!m) return line;
  const who = m[1][0].toUpperCase() + m[1].slice(1).toLowerCase();
  return `${who}: ${m[2].trim()}`;
}

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
