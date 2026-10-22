import { useCallback, useEffect, useState, type ReactNode } from "react";
import { clsx } from "clsx";
import { CheckCircle2, AlertCircle, X } from "lucide-react";

export interface ToastProps {
  title?: string;
  description?: string;
  variant?: "default" | "destructive";
  duration?: number;
}

interface ToastItem extends ToastProps {
  id: number;
}

type ToastListener = (props: ToastProps) => void;

const listeners = new Set<ToastListener>();

export function toast(props: ToastProps) {
  listeners.forEach((listener) => listener(props));
}

let toastId = 0;

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<ToastItem[]>([]);

  const dismiss = useCallback((id: number) => {
    setToasts((prev) => prev.filter((t) => t.id !== id));
  }, []);

  const toastFn = useCallback(
    (props: ToastProps) => {
      const id = ++toastId;
      setToasts((prev) => [...prev, { ...props, id }]);
      const duration = props.duration ?? 5000;
      setTimeout(() => dismiss(id), duration);
    },
    [dismiss]
  );

  useEffect(() => {
    listeners.add(toastFn);
    return () => {
      listeners.delete(toastFn);
    };
  }, [toastFn]);

  return (
    <>
      {children}
      <ToastViewport toasts={toasts} onDismiss={dismiss} />
    </>
  );
}

export function useToast() {
  return { toast: toastFnSafe };
}

const toastFnSafe = (props: ToastProps) => toast(props);

function ToastViewport({
  toasts,
  onDismiss,
}: {
  toasts: ToastItem[];
  onDismiss: (id: number) => void;
}) {
  return (
    <div className="fixed bottom-0 right-0 z-[100] flex flex-col gap-2 p-4 w-full max-w-sm pointer-events-none">
      {toasts.map((t) => (
        <div
          key={t.id}
          className={clsx(
            "pointer-events-auto flex items-start gap-3 rounded-lg border p-4 shadow-lg animate-in slide-in-from-bottom-2",
            t.variant === "destructive"
              ? "bg-red-50 border-red-200 text-red-900"
              : "bg-white border-gray-200 text-gray-900"
          )}
        >
          {t.variant === "destructive" ? (
            <AlertCircle className="h-5 w-5 text-red-600 flex-shrink-0 mt-0.5" />
          ) : (
            <CheckCircle2 className="h-5 w-5 text-green-600 flex-shrink-0 mt-0.5" />
          )}
          <div className="flex-1 min-w-0">
            {t.title && <p className="font-medium text-sm">{t.title}</p>}
            {t.description && (
              <p className="text-sm opacity-80 mt-0.5">{t.description}</p>
            )}
          </div>
          <button
            onClick={() => onDismiss(t.id)}
            className="text-gray-400 hover:text-gray-600 flex-shrink-0"
            aria-label="Dismiss notification"
          >
            <X className="h-4 w-4" />
          </button>
        </div>
      ))}
    </div>
  );
}