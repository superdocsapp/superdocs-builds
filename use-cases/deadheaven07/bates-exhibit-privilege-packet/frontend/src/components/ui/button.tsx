import { ButtonHTMLAttributes, forwardRef } from "react";
import { clsx } from "clsx";

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: "default" | "outline" | "ghost" | "destructive" | "secondary";
  size?: "sm" | "md" | "lg";
}

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(
  ({ className, variant = "default", size = "md", disabled, children, ...props }, ref) => {
    const baseStyles = "inline-flex items-center justify-center font-medium rounded-xl transition-all duration-200 focus:outline-none focus:ring-2 focus:ring-sky-500/50 focus:ring-offset-2 dark:focus:ring-offset-slate-950 focus:ring-offset-white disabled:opacity-50 disabled:pointer-events-none active:scale-[0.98]";

    const variants = {
      default: "bg-gradient-to-r from-sky-500 to-indigo-600 hover:from-sky-400 hover:to-indigo-500 text-white shadow-glow-sm hover:shadow-glow-md",
      secondary: "dark:bg-slate-800 dark:hover:bg-slate-700 dark:text-slate-100 dark:border-slate-700/80 bg-slate-100 hover:bg-slate-200 text-slate-800 border border-slate-200/90 shadow-sm",
      outline: "dark:border-slate-700 dark:bg-slate-900/80 dark:text-slate-200 dark:hover:bg-slate-800 dark:hover:text-white border-slate-300 bg-white text-slate-700 hover:bg-slate-50 hover:text-slate-900 shadow-sm border",
      ghost: "dark:text-slate-400 dark:hover:text-slate-100 dark:hover:bg-slate-800/60 text-slate-600 hover:text-slate-900 hover:bg-slate-100",
      destructive: "bg-rose-600 hover:bg-rose-500 text-white shadow-sm",
    };

    const sizes = {
      sm: "px-3 py-1.5 text-xs gap-1.5",
      md: "px-4 py-2 text-sm gap-2",
      lg: "px-5 py-2.5 text-base gap-2.5",
    };

    return (
      <button
        ref={ref}
        className={clsx(baseStyles, variants[variant], sizes[size], className)}
        disabled={disabled}
        {...props}
      >
        {children}
      </button>
    );
  }
);

Button.displayName = "Button";