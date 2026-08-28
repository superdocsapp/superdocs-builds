import { useEffect, useState } from "react";

export interface ToastProps {
  /** Message to display in the toast notification */
  message: string;
  /** Whether the toast is visible */
  visible: boolean;
  /** Called when the toast auto-dismisses or is manually dismissed */
  onDismiss: () => void;
  /** Auto-dismiss duration in milliseconds (default: 4000) */
  duration?: number;
  /** Visual variant for the toast */
  variant?: "info" | "error" | "warning";
}

const VARIANT_STYLES: Record<string, string> = {
  info: "border-indigo-500/20 text-indigo-200 shadow-indigo-500/10",
  error: "border-rose-500/20 text-rose-200 shadow-rose-500/10",
  warning: "border-amber-500/20 text-amber-200 shadow-amber-500/10",
};

/**
 * A simple auto-dismissing toast notification component.
 * Used to display brief feedback messages such as "already decided" conflicts.
 */
export function Toast({
  message,
  visible,
  onDismiss,
  duration = 4000,
  variant = "info",
}: ToastProps) {
  const [show, setShow] = useState(visible);

  useEffect(() => {
    setShow(visible);
  }, [visible]);

  useEffect(() => {
    if (!show) return;

    const timer = setTimeout(() => {
      setShow(false);
      onDismiss();
    }, duration);

    return () => clearTimeout(timer);
  }, [show, duration, onDismiss]);

  if (!show) return null;

  return (
    <div
      role="status"
      aria-live="polite"
      aria-atomic="true"
      className={`fixed bottom-4 right-4 z-50 flex items-center gap-2 rounded-xl border bg-surface-elevated/95 px-4 py-3 shadow-2xl backdrop-blur-xl ${VARIANT_STYLES[variant]}`}
    >
      <span className="text-sm font-medium">{message}</span>
      <button
        type="button"
        onClick={() => {
          setShow(false);
          onDismiss();
        }}
        aria-label="Dismiss notification"
        className="ml-2 rounded-lg p-1 text-current opacity-50 transition-opacity hover:opacity-100 focus:outline-none focus:ring-2 focus:ring-white/20"
      >
        <svg className="h-3.5 w-3.5" fill="none" viewBox="0 0 24 24" strokeWidth={2} stroke="currentColor">
          <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
        </svg>
      </button>
    </div>
  );
}
