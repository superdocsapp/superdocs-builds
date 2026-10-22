import { useContext } from "react";
import { ThemeContext, type ThemeContextType } from "@/context/ThemeContext";

export function useTheme(): ThemeContextType {
  const context = useContext(ThemeContext);
  if (!context) {
    throw new Error("useTheme must be used within a ThemeProvider");
  }
  return context;
}

export { ThemeProvider, type Theme } from "@/context/ThemeContext";
