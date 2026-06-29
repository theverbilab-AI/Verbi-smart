/**
 * Demo / client-facing QA display (revert via env — no DB or scoring logic changes).
 *
 * VITE_KPI_DISPLAY_MAX=10   → show KPI scores as /10 instead of native /2,/3,/1
 * VITE_KPI_MASK_NAMES=1     → show P1,P2,… instead of Opening, Probing, etc.
 */

export const KPI_DISPLAY_MAX = Number(import.meta.env.VITE_KPI_DISPLAY_MAX || 3);

export const KPI_MASK_CLIENT_NAMES =
  String(import.meta.env.VITE_KPI_MASK_CLIENT_NAMES || "")
    .trim()
    .toLowerCase() === "true" ||
  import.meta.env.VITE_KPI_MASK_CLIENT_NAMES === "1";

/** Native max scores — must match backend scoring_rules / processor caps. */
export const NATIVE_KPI_MAX = {
  A1_opening: 2,
  A2_case_knowledge: 2,
  A3_probing: 3,
  A4_negotiation: 3,
  A5_commitment_ptp: 3,
  A6_closing: 2,
  A7_professionalism: 3,
  A8_call_handling: 1,
  A9_troubleshooting: 1,
};

const OPENING_ITEMS = [
  { key: "disclaimer_given", label: "Disclaimer" },
  { key: "agent_intro_done", label: "Agent intro" },
  { key: "customer_name_used", label: "Customer name" },
  { key: "rpc_confirmed", label: "RPC confirmed" },
];

export function getDisplayMax(nativeMax) {
  const n = Number(nativeMax) || 1;
  const d = Number(KPI_DISPLAY_MAX) || n;
  return d > 0 ? d : n;
}

/** Scale raw score to demo display max (e.g. 2/2 → 10/10 when max=10). */
export function formatKpiScore(rawScore, nativeMax) {
  const raw = Number(rawScore) || 0;
  const native = Number(nativeMax) || 1;
  const displayMax = getDisplayMax(native);
  if (displayMax === native) {
    return { score: raw, max: native, pct: native ? (raw / native) * 100 : 0 };
  }
  const score = Math.round((raw / native) * displayMax);
  return {
    score: Math.max(0, Math.min(displayMax, score)),
    max: displayMax,
    pct: displayMax ? (score / displayMax) * 100 : 0,
  };
}

export function maskKpiLabel(key, defaultLabel, index = 0) {
  if (!KPI_MASK_CLIENT_NAMES) return defaultLabel;
  if (key && /^A\d_/i.test(key)) {
    const n = parseInt(key.split("_")[0].replace(/\D/g, ""), 10);
    if (n >= 1 && n <= 9) return `P${n}`;
  }
  return `P${index + 1}`;
}

export function maskSalesKpiLabel(index, defaultName) {
  if (!KPI_MASK_CLIENT_NAMES) return defaultName;
  return `P${index + 1}`;
}

export function getOpeningAuditItems() {
  return OPENING_ITEMS.map((item, i) => ({
    ...item,
    label: KPI_MASK_CLIENT_NAMES ? `P${i + 1}` : item.label,
  }));
}

export function collectionsKpiKeys() {
  return Object.keys(NATIVE_KPI_MAX);
}
