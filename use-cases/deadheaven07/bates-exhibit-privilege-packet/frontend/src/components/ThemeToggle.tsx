import { Sun, Moon } from "lucide-react";
import { useTheme } from "@/hooks/useTheme";
import { clsx } from "clsx";

interface ThemeToggleProps {
  id?: string;
  className?: string;
  showLabel?: boolean;
  size?: "sm" | "md";
}

export function ThemeToggle({ id, className, showLabel = true, size = "md" }: ThemeToggleProps) {
  const { theme, toggleTheme } = useTheme();
  const isDark = theme === "dark";

  return (
    <button
      id={id}
      type="button"
      onClick={toggleTheme}
      aria-label={isDark ? "Switch to Light Mode" : "Switch to Dark Mode"}
      title={isDark ? "Switch to Light Mode" : "Switch to Dark Mode"}
      className={clsx(
        "group relative flex items-center justify-between rounded-xl transition-all duration-200 outline-none focus:ring-2 focus:ring-sky-500/50 cursor-pointer select-none",
        isDark
          ? "bg-slate-900 border border-slate-700/80 text-slate-300 hover:text-white hover:border-slate-600 shadow-sm"
          : "bg-white border border-slate-200 text-slate-700 hover:text-slate-900 hover:border-slate-300 shadow-sm",
        size === "sm" ? "px-2.5 py-1 text-xs gap-1.5" : "px-3 py-1.5 text-xs gap-2",
        className
      )}
    >
      <div className="flex items-center gap-2">
        <div
          className={clsx(
            "flex items-center justify-center rounded-lg p-1 transition-all duration-300 transform",
            isDark
              ? "bg-indigo-500/20 text-amber-300 group-hover:rotate-45"
              : "bg-amber-100 text-amber-600 group-hover:rotate-45"
          )}
        >
          {isDark ? (
            <Moon className={size === "sm" ? "h-3.5 w-3.5" : "h-4 w-4"} />
          ) : (
            <Sun className={size === "sm" ? "h-3.5 w-3.5" : "h-4 w-4"} />
          )}
        </div>
        {showLabel && (
          <span className="font-medium tracking-tight">
            {isDark ? "Dark Mode" : "Light Mode"}
          </span>
        )}
      </div>

      <div
        className={clsx(
          "w-8 h-4 rounded-full p-0.5 transition-colors duration-200 flex items-center shrink-0",
          isDark ? "bg-indigo-600 justify-end" : "bg-slate-300 justify-start"
        )}
      >
        <div className="w-3 h-3 rounded-full bg-white shadow-sm transition-transform duration-200"></div>
      </div>
    </button>
  );
}
