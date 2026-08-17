import { Icon } from "./Icon";
import { useNotifications } from "../notifications/NotificationContext";

export function ToastStack() {
  const { toasts, dismiss } = useNotifications();

  if (toasts.length === 0) return null;

  return (
    <div className="toast-stack">
      {toasts.map((t) => (
        <div key={t.id} className={`toast toast-${t.tone}`}>
          <div className="toast-icon">
            {t.tone === "success" && <Icon name="check" size={16} />}
            {t.tone === "error" && <Icon name="close" size={16} />}
            {t.tone === "info" && <span className="spinner" aria-hidden="true" />}
          </div>
          <div className="toast-body">
            <p className="toast-title">{t.title}</p>
            {t.subtitle && <p className="toast-subtitle">{t.subtitle}</p>}
          </div>
          <button
            type="button"
            className="toast-dismiss"
            onClick={() => dismiss(t.id)}
            aria-label="Dismiss"
          >
            <Icon name="close" size={12} />
          </button>
        </div>
      ))}
    </div>
  );
}