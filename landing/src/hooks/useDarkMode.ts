import { useCallback, useEffect, useState } from "react";

type Theme = "dark" | "light";

const STORAGE_KEY = "lodgeos-theme";

function getInitial(): Theme {
  if (typeof window === "undefined") return "dark";
  const stored = localStorage.getItem(STORAGE_KEY) as Theme | null;
  if (stored) return stored;
  return window.matchMedia("(prefers-color-scheme: light)").matches ? "light" : "dark";
}

export function useDarkMode() {
  const [theme, setTheme] = useState<Theme>(getInitial);

  useEffect(() => {
    const root = document.documentElement;
    root.classList.toggle("dark", theme === "dark");
    localStorage.setItem(STORAGE_KEY, theme);
  }, [theme]);

  const toggle = useCallback(() => setTheme((t) => (t === "dark" ? "light" : "dark")), []);

  return { theme, toggle, isDark: theme === "dark" };
}
