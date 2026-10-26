import { createContext, useCallback, useContext, useState, type ReactNode } from "react";

export type ToastTone = "success" | "error" | "info";

export interface Toast {
  id: string;
  title: string;
  subtitle?: string;
  tone: ToastTone;
}

interface NotificationState {
  toasts: Toast[];
  notify: (title: string, subtitle?: string, tone?: ToastTone) => void;
  dismiss: (id: string) => void;
}

const NotificationContext = createContext<NotificationState | null>(null);
const LINGER_MS = 5000;

export function NotificationProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);

  const dismiss = useCallback((id: string) => {
    setToasts((current) => current.filter((t) => t.id !== id));
  }, []);

  const notify = useCallback(
    (title: string, subtitle?: string, tone: ToastTone = "info") => {
      const id = `${Date.now()}-${Math.random().toString(36).slice(2)}`;
      setToasts((current) => [...current, { id, title, subtitle, tone }]);
      setTimeout(() => dismiss(id), LINGER_MS);
    },
    [dismiss]
  );

  return (
    <NotificationContext.Provider value={{ toasts, notify, dismiss }}>
      {children}
    </NotificationContext.Provider>
  );
}

export function useNotifications(): NotificationState {
  const ctx = useContext(NotificationContext);
  if (!ctx) throw new Error("useNotifications must be used within a NotificationProvider");
  return ctx;
}