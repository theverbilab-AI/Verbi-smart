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

/** Split merged Agent/Customer lines (mirrors backend repair). */
export function repairDiarization(labelled) {
  if (!labelled) return labelled;

  const splitCustomer =
    /(?<=[.!?,])\s+(?=no\.?\s*who is speaking|who is speaking|the call got disconnected|i am saying|customer:|tell me,?\s*by when|yes,?\s*tell me|madam,?\s+we are|madam,?\s+i |sir,?\s+your app|can you send|like we deposit|what is not available)/i;
  const splitAgent =
    /(?<=[.!?,])\s+(?=good (?:morning|afternoon|evening)|speaking on behalf|this is|sir,?\s*i am|madam,?\s*i am|agent:|hello hello)/i;

  const repaired = [];
  for (const raw of labelled.split(/\r?\n/)) {
    const line = raw.trim();
    if (!line) continue;
    const m = line.match(/^(agent|customer)\s*:\s*(.*)$/i);
    if (!m) {
      repaired.push(line);
      continue;
    }
    const speaker = m[1][0].toUpperCase() + m[1].slice(1).toLowerCase();
    const text = m[2].trim();
    if (text.length < 45) {
      repaired.push(`${speaker}: ${text}`);
      continue;
    }
    const splitter = speaker === "Agent" ? splitCustomer : splitAgent;
    const parts = text.split(splitter);
    if (parts.length <= 1) {
      repaired.push(`${speaker}: ${text}`);
      continue;
    }
    const alt = speaker === "Agent" ? "Customer" : "Agent";
    repaired.push(`${speaker}: ${parts[0].trim()}`);
    for (let i = 1; i < parts.length; i++) {
      const part = parts[i].trim();
      if (part) repaired.push(`${alt}: ${part}`);
    }
  }
  return repaired.join("\n");
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

  if (lines.length) return repairDiarization(lines.join("\n"));

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
