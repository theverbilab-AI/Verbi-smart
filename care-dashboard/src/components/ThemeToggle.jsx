import { Moon, Sun } from "lucide-react";
import { useEffect, useState } from "react";
import { applyTheme, getTheme } from "../utils/theme";

export default function ThemeToggle({ className = "" }) {
  const [theme, setTheme] = useState(() => getTheme());

  useEffect(() => {
    const onStorage = (e) => {
      if (e.key === "care_theme" && e.newValue) setTheme(e.newValue);
    };
    window.addEventListener("storage", onStorage);
    return () => window.removeEventListener("storage", onStorage);
  }, []);

  const flip = () => {
    const next = applyTheme(theme === "dark" ? "light" : "dark");
    setTheme(next);
  };

  return (
    <button
      type="button"
      onClick={flip}
      className={`p-2.5 rounded-lg text-slate-400 hover:text-slate-100 hover:bg-slate-800 transition-colors theme-toggle-btn ${className}`}
      title={theme === "dark" ? "Switch to light mode" : "Switch to dark mode"}
      aria-label={theme === "dark" ? "Switch to light mode" : "Switch to dark mode"}
    >
      {theme === "dark" ? <Sun className="w-5 h-5" /> : <Moon className="w-5 h-5" />}
    </button>
  );
}
