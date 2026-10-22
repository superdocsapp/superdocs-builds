import React from "react";
import { clsx } from "clsx";

interface BadgeProps {
  children: React.ReactNode;
  variant?: "default" | "success" | "warning" | "danger" | "purple" | "indigo" | "outline";
  size?: "sm" | "md";
  className?: string;
  icon?: React.ReactNode;
}

export function Badge({
  children,
  variant = "default",
  size = "sm",
  className,
  icon,
}: BadgeProps) {
  const variantStyles = {
    default: "dark:bg-slate-800 dark:text-slate-300 dark:border-slate-700/80 bg-slate-100 text-slate-700 border-slate-300",
    success: "dark:bg-emerald-950/70 dark:text-emerald-300 dark:border-emerald-800/60 bg-emerald-50 text-emerald-700 border-emerald-300 shadow-sm",
    warning: "dark:bg-amber-950/70 dark:text-amber-300 dark:border-amber-800/60 bg-amber-50 text-amber-700 border-amber-300 shadow-sm",
    danger: "dark:bg-rose-950/70 dark:text-rose-300 dark:border-rose-800/60 bg-rose-50 text-rose-700 border-rose-300 shadow-sm",
    purple: "dark:bg-purple-950/70 dark:text-purple-300 dark:border-purple-800/60 bg-purple-50 text-purple-700 border-purple-300 shadow-sm",
    indigo: "dark:bg-indigo-950/70 dark:text-indigo-300 dark:border-indigo-800/60 bg-indigo-50 text-indigo-700 border-indigo-300 shadow-sm",
    outline: "bg-transparent dark:text-slate-400 text-slate-600 dark:border-slate-700 border-slate-300 dark:hover:border-slate-500 hover:border-slate-400",
  }[variant];

  const sizeStyles = {
    sm: "px-2 py-0.5 text-xs font-medium",
    md: "px-2.5 py-1 text-xs font-semibold tracking-wide",
  }[size];

  return (
    <span
      className={clsx(
        "inline-flex items-center gap-1.5 rounded-full border transition-all duration-150",
        variantStyles,
        sizeStyles,
        className
      )}
    >
      {icon && <span className="shrink-0">{icon}</span>}
      <span>{children}</span>
    </span>
  );
}
