import { useEffect } from "react";
import { CheckCircle2, Info, AlertTriangle, X } from "lucide-react";
import clsx from "clsx";
import { useAppStore, type Toast as ToastRecord } from "../../store/appStore";

const ICONS: Record<ToastRecord["kind"], typeof CheckCircle2> = {
  success: CheckCircle2,
  info: Info,
  warning: AlertTriangle,
};

const ICON_TONE: Record<ToastRecord["kind"], string> = {
  success: "text-verified",
  info: "text-trust",
  warning: "text-warning",
};

function ToastItem({ toast }: { toast: ToastRecord }) {
  const dismissToast = useAppStore((s) => s.dismissToast);

  useEffect(() => {
    const timer = setTimeout(() => dismissToast(toast.id), 4500);
    return () => clearTimeout(timer);
  }, [toast.id, dismissToast]);

  const Icon = ICONS[toast.kind];

  return (
    <div
      role="status"
      className="shadow-elevated flex w-80 items-start gap-3 rounded-md border border-line bg-paper-0 p-3"
      style={{ animation: "sd-toast-in 200ms ease-out" }}
    >
      <Icon className={clsx("mt-0.5 h-4 w-4 shrink-0", ICON_TONE[toast.kind])} aria-hidden="true" />
      <div className="min-w-0 flex-1">
        <p className="text-sm font-medium text-text-primary">{toast.title}</p>
        {toast.description && <p className="mt-0.5 line-clamp-2 text-xs text-text-tertiary">{toast.description}</p>}
      </div>
      <button
        onClick={() => dismissToast(toast.id)}
        aria-label="Dismiss notification"
        className="shrink-0 rounded p-1 text-text-tertiary transition-colors hover:bg-paper-100 hover:text-text-primary"
      >
        <X className="h-3.5 w-3.5" aria-hidden="true" />
      </button>
    </div>
  );
}

export function ToastViewport() {
  const toasts = useAppStore((s) => s.toasts);
  return (
    <div aria-live="polite" aria-atomic="false" className="pointer-events-none fixed bottom-4 right-4 z-[60] flex flex-col gap-2">
      {toasts.map((toast) => (
        <div key={toast.id} className="pointer-events-auto">
          <ToastItem toast={toast} />
        </div>
      ))}
    </div>
  );
}
