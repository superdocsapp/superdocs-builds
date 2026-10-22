import React, { useEffect } from "react";
import { X } from "lucide-react";
import { clsx } from "clsx";

interface ModalProps {
  isOpen: boolean;
  onClose: () => void;
  title: React.ReactNode;
  description?: React.ReactNode;
  children: React.ReactNode;
  footer?: React.ReactNode;
  maxWidth?: "sm" | "md" | "lg" | "xl" | "2xl";
}

export function Modal({
  isOpen,
  onClose,
  title,
  description,
  children,
  footer,
  maxWidth = "lg",
}: ModalProps) {
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

  const maxWidthClasses = {
    sm: "max-w-sm",
    md: "max-w-md",
    lg: "max-w-lg",
    xl: "max-w-xl",
    "2xl": "max-w-2xl",
  }[maxWidth];

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 sm:p-6 overflow-y-auto">
      {/* Backdrop with blur */}
      <div
        className="fixed inset-0 dark:bg-slate-950/80 bg-slate-900/40 backdrop-blur-md transition-opacity duration-300 animate-fade-in"
        onClick={onClose}
        aria-hidden="true"
      />

      {/* Modal Card */}
      <div
        className={clsx(
          "relative w-full dark:bg-slate-900 bg-white dark:border-slate-800/90 border-slate-200 border rounded-2xl shadow-2xl dark:shadow-slate-950/80 shadow-slate-400/20",
          "p-6 dark:text-slate-100 text-slate-900 transform transition-all duration-300 animate-slide-up z-10",
          maxWidthClasses
        )}
        role="dialog"
        aria-modal="true"
      >
        {/* Header */}
        <div className="flex items-start justify-between pb-4 border-b dark:border-slate-800/80 border-slate-200/80">
          <div>
            <h3 className="text-lg font-semibold tracking-tight dark:text-slate-100 text-slate-900 font-display">
              {title}
            </h3>
            {description && (
              <p className="mt-1 text-xs dark:text-slate-400 text-slate-500 leading-relaxed">
                {description}
              </p>
            )}
          </div>
          <button
            onClick={onClose}
            className="rounded-lg p-1.5 dark:text-slate-400 dark:hover:text-slate-200 dark:hover:bg-slate-800 text-slate-500 hover:text-slate-900 hover:bg-slate-100 transition-colors focus:outline-none focus:ring-2 focus:ring-indigo-500"
            title="Close"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* Content Body */}
        <div className="py-4 max-h-[70vh] overflow-y-auto pr-1">
          {children}
        </div>

        {/* Footer */}
        {footer && (
          <div className="flex items-center justify-end gap-3 pt-4 border-t dark:border-slate-800/80 border-slate-200/80">
            {footer}
          </div>
        )}
      </div>
    </div>
  );
}
