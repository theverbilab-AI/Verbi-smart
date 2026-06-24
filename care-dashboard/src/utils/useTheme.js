import { useEffect, useState } from "react";
import { getTheme } from "./theme";

export function useTheme() {
  const [theme, setTheme] = useState(() => getTheme());

  useEffect(() => {
    const sync = () => {
      setTheme(document.documentElement.getAttribute("data-theme") || getTheme());
    };
    sync();
    const obs = new MutationObserver(sync);
    obs.observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });
    window.addEventListener("storage", sync);
    return () => {
      obs.disconnect();
      window.removeEventListener("storage", sync);
    };
  }, []);

  return theme;
}
