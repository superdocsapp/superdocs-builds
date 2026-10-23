import { useEffect, useState } from "react";

import { applyTheme, getStoredTheme, toggleTheme, type Theme } from "@/lib/theme";

export function useTheme() {
  const [theme, setTheme] = useState<Theme>("light");

  useEffect(() => {
    const initial = getStoredTheme();
    applyTheme(initial);
    setTheme(initial);
  }, []);

  function onToggle() {
    setTheme((current) => toggleTheme(current));
  }

  return { theme, toggle: onToggle, isDark: theme === "dark" };
}
