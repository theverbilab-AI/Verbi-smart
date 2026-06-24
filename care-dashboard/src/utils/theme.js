const STORAGE_KEY = "care_theme";

export function getTheme() {
  if (typeof window === "undefined") return "dark";
  const stored = localStorage.getItem(STORAGE_KEY);
  if (stored === "light" || stored === "dark") return stored;
  return window.matchMedia?.("(prefers-color-scheme: light)")?.matches ? "light" : "dark";
}

export function applyTheme(theme) {
  const next = theme === "light" ? "light" : "dark";
  document.documentElement.setAttribute("data-theme", next);
  localStorage.setItem(STORAGE_KEY, next);
  return next;
}

export function initTheme() {
  return applyTheme(getTheme());
}

export function toggleTheme() {
  return applyTheme(getTheme() === "dark" ? "light" : "dark");
}

/** Recharts + tooltip colors for current theme */
export function getChartTheme(theme = getTheme()) {
  const light = theme === "light";
  return {
    grid: light ? "#e2e8f0" : "#1e293b",
    tick: light ? "#475569" : "#94a3b8",
    tickBright: light ? "#1e293b" : "#cbd5e1",
    tooltipBg: light ? "rgba(255,255,255,0.98)" : "rgba(15,23,42,0.95)",
    tooltipBorder: light ? "#cbd5e1" : "#334155",
    tooltipTitle: light ? "#0f172a" : "#e2e8f0",
    tooltipValue: light ? "#0891b2" : "#67e8f9",
    pieStroke: light ? "#f8fafc" : "#0f172a",
    legendColor: light ? "#475569" : "#cbd5e1",
  };
}
