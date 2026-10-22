import React, { useEffect } from "react";
import { X } from "lucide-react";
import { clsx } from "clsx";

interface DrawerProps {
  isOpen: boolean;
  onClose: () => void;
  title: React.ReactNode;
  subtitle?: React.ReactNode;
  children: React.ReactNode;
  footer?: React.ReactNode;
  width?: "md" | "lg" | "xl" | "2xl";
}

export function Drawer({
  isOpen,
  onClose,
  title,
  subtitle,
  children,
  footer,
  width = "xl",
}: DrawerProps) {
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape" && isOpen) {
        onClose();
      }
    };
    if (isOpen) {
      document.body.style.overflow = "hidden";
      window.addEventListener("keydown", handleKeyDown);
    }
    return () => {
      document.body.style.overflow = "unset";
      window.removeEventListener("keydown", handleKeyDown);
    };
  }, [isOpen, onClose]);

  if (!isOpen) return null;

  const widthClasses = {
    md: "max-w-md",
    lg: "max-w-lg",
    xl: "max-w-xl",
    "2xl": "max-w-2xl",
  }[width];

  return (
    <div className="fixed inset-0 z-50 overflow-hidden">
      {/* Backdrop */}
      <div
        className="fixed inset-0 dark:bg-slate-950/75 bg-slate-900/40 backdrop-blur-sm transition-opacity duration-300 animate-fade-in"
        onClick={onClose}
        aria-hidden="true"
      />

      <div className="fixed inset-y-0 right-0 max-w-full flex pl-10">
        <div
          className={clsx(
            "w-screen dark:bg-slate-900 bg-white dark:border-slate-800 border-slate-200 border-l shadow-2xl dark:shadow-slate-950/90 shadow-slate-400/20 flex flex-col transform transition-transform duration-300 ease-in-out",
            widthClasses
          )}
        >
          {/* Header */}
          <div className="p-6 border-b dark:border-slate-800/90 border-slate-200/90 dark:bg-slate-900/95 bg-white/95 backdrop-blur flex items-start justify-between">
            <div className="space-y-1">
              <div className="text-lg font-semibold dark:text-slate-100 text-slate-900 font-display flex items-center gap-2">
                {title}
              </div>
              {subtitle && (
                <div className="text-xs dark:text-slate-400 text-slate-500">
                  {subtitle}
                </div>
              )}
            </div>
            <button
              onClick={onClose}
              className="rounded-lg p-2 dark:text-slate-400 dark:hover:text-slate-200 dark:hover:bg-slate-800 text-slate-500 hover:text-slate-900 hover:bg-slate-100 transition-colors focus:outline-none focus:ring-2 focus:ring-indigo-500"
              title="Close drawer"
            >
              <X className="w-5 h-5" />
            </button>
          </div>

          {/* Drawer Body */}
          <div className="flex-1 overflow-y-auto p-6 space-y-6 dark:text-slate-200 text-slate-800">
            {children}
          </div>

          {/* Footer */}
          {footer && (
            <div className="p-4 border-t dark:border-slate-800 border-slate-200 dark:bg-slate-900/90 bg-slate-50/90 flex items-center justify-end gap-3">
              {footer}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
