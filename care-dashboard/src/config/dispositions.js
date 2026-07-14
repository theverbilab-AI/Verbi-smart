/** Collections disposition labels — keys match care-backend scoring_rules / DB. */
export const DISPOSITION_LABELS = {
  PTP: "PTP (Promise to Pay)",
  NO_PTP: "No PTP",
  CALLBACK: "Callback",
  REFUSED_TO_PAY: "Refused to Pay",
  FINANCIAL_HARDSHIP: "Financial Hardship",
  MEDICAL_ISSUE: "Medical Issue",
  DISPUTE: "Dispute",
  SETTLEMENT_REQUEST: "Settlement Request",
  APP_ISSUE: "App / Payment Issue",
  APP_NOT_WORKING: "App / Payment Issue",
  PAYMENT_ISSUE: "App / Payment Issue",
  LANGUAGE_ISSUE: "Language Issue",
  DISCONNECTED: "Disconnected",
  THIRD_PARTY: "Third Party",
  WRONG_NUMBER: "Wrong Number",
  LEGAL_ESCALATION: "Legal Escalation",
  NO_RESPONSE: "No Response",
  OTHER: "Other",
};

/** Primary disposition keys shown in filter dropdown (deduped labels). */
export const DISPOSITION_FILTER_OPTIONS = [
  "PTP",
  "NO_PTP",
  "CALLBACK",
  "REFUSED_TO_PAY",
  "FINANCIAL_HARDSHIP",
  "MEDICAL_ISSUE",
  "DISPUTE",
  "SETTLEMENT_REQUEST",
  "APP_ISSUE",
  "LANGUAGE_ISSUE",
  "DISCONNECTED",
  "THIRD_PARTY",
  "WRONG_NUMBER",
  "LEGAL_ESCALATION",
  "NO_RESPONSE",
  "OTHER",
];

/** Top-row disposition KPI cards for collections dashboard. */
export const COLLECTIONS_DISPOSITION_KPIS = [
  { keys: ["NO_PTP"], label: "No PTP", accent: "text-amber-300" },
  { keys: ["CALLBACK"], label: "Callback", accent: "text-blue-300" },
  { keys: ["REFUSED_TO_PAY"], label: "Refused to Pay", accent: "text-red-300" },
  { keys: ["FINANCIAL_HARDSHIP"], label: "Financial Hardship", accent: "text-orange-300" },
  { keys: ["DISPUTE"], label: "Dispute", accent: "text-rose-300" },
  { keys: ["WRONG_NUMBER"], label: "Wrong Number", accent: "text-slate-400" },
];

export function normalizeDisposition(v) {
  return String(v || "OTHER").trim().toUpperCase().replace(/[\s-]+/g, "_");
}

export function labelDisposition(v) {
  return DISPOSITION_LABELS[normalizeDisposition(v)] || String(v || "Other");
}
