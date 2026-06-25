import { useEffect, useState } from "react";

const KEY = "care-audit-mode";
const EVT = "care-audit-mode-change";

export const AUDIT_MODES = ["collections", "sales"];

export function getAuditMode() {
  try {
    const v = (localStorage.getItem(KEY) || "collections").toLowerCase();
    return v === "sales" ? "sales" : "collections";
  } catch {
    return "collections";
  }
}

export function setAuditMode(mode) {
  const m = mode === "sales" ? "sales" : "collections";
  try {
    localStorage.setItem(KEY, m);
  } catch {
    /* ignore */
  }
  window.dispatchEvent(new CustomEvent(EVT, { detail: m }));
}

/** React hook: returns [mode, setMode]. Re-renders on global mode change. */
export function useAuditMode() {
  const [mode, setMode] = useState(getAuditMode);
  useEffect(() => {
    const sync = () => setMode(getAuditMode());
    window.addEventListener(EVT, sync);
    window.addEventListener("storage", sync);
    return () => {
      window.removeEventListener(EVT, sync);
      window.removeEventListener("storage", sync);
    };
  }, []);
  return [mode, setAuditMode];
}

/** The audit mode of a single call record (defaults to collections). */
export function callAuditMode(call) {
  const m = String(call?.analysis?.audit_mode || "collections").toLowerCase();
  return m === "sales" ? "sales" : "collections";
}

/** Filter a list of calls to a single audit mode. */
export function filterCallsByMode(calls, mode) {
  const want = mode === "sales" ? "sales" : "collections";
  return (Array.isArray(calls) ? calls : []).filter((c) => callAuditMode(c) === want);
}
