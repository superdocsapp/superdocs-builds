import type { ReactNode } from "react";
import clsx from "clsx";
import { useFocusTrap } from "../../hooks/useFocusTrap";

export function Modal({
  open,
  onClose,
  title,
  children,
  maxWidthClassName = "max-w-md",
}: {
  open: boolean;
  onClose: () => void;
  title: string;
  children: ReactNode;
  maxWidthClassName?: string;
}) {
  const containerRef = useFocusTrap<HTMLDivElement>(open, onClose);

  if (!open) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
      <button
        aria-label="Close dialog"
        onClick={onClose}
        className="absolute inset-0 bg-ink-950/40"
        style={{ animation: "sd-fade-in 150ms ease-out" }}
      />
      <div
        ref={containerRef}
        role="dialog"
        aria-modal="true"
        aria-label={title}
        tabIndex={-1}
        className={clsx("shadow-elevated relative w-full rounded-md bg-paper-0 focus:outline-none", maxWidthClassName)}
        style={{ animation: "sd-pop-in 160ms ease-out" }}
      >
        {children}
      </div>
    </div>
  );
}

export function ConfirmDialog({
  open,
  onClose,
  onConfirm,
  title,
  description,
  confirmLabel = "Confirm",
  cancelLabel = "Cancel",
  tone = "default",
  confirmDisabled = false,
}: {
  open: boolean;
  onClose: () => void;
  onConfirm: () => void;
  title: string;
  description?: ReactNode;
  confirmLabel?: string;
  cancelLabel?: string;
  tone?: "default" | "critical";
  confirmDisabled?: boolean;
}) {
  return (
    <Modal open={open} onClose={onClose} title={title}>
      <div className="px-5 py-4">
        <h2 className="text-sm font-semibold text-text-primary">{title}</h2>
        {description && <div className="mt-2 text-sm leading-relaxed text-text-secondary">{description}</div>}
      </div>
      <div className="flex justify-end gap-2 border-t border-line px-5 py-3">
        <button onClick={onClose} className="rounded-md px-3 py-1.5 text-sm font-medium text-text-secondary transition-colors hover:bg-paper-100">
          {cancelLabel}
        </button>
        <button
          onClick={onConfirm}
          disabled={confirmDisabled}
          className={clsx(
            "rounded-md px-3 py-1.5 text-sm font-medium text-white transition-colors disabled:cursor-not-allowed disabled:opacity-50",
            tone === "critical" ? "bg-critical hover:bg-critical/90" : "bg-trust hover:bg-trust-strong",
          )}
        >
          {confirmLabel}
        </button>
      </div>
    </Modal>
  );
}
