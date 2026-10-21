import { useEffect, useRef } from "react";
import { PRIMARY_LINKS } from "../nav";
import { useDialogA11y } from "../hooks/useDialogA11y";
import { IconClose, IconDocs, IconMark } from "./icons";
import { SidebarNavItem } from "./SidebarNavItem";

export function MobileNavDrawer({
  open,
  onClose,
  onOpenEvidence,
}: {
  open: boolean;
  onClose: () => void;
  onOpenEvidence: () => void;
}) {
  const sheetRef = useRef<HTMLDivElement>(null);
  const closeRef = useRef<HTMLButtonElement>(null);
  useDialogA11y(open, onClose, sheetRef, closeRef);

  useEffect(() => {
    if (!open) return;
    const previous = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.body.style.overflow = previous;
    };
  }, [open]);

  if (!open) return null;

  return (
    <div className="mobile-nav" role="presentation">
      <button type="button" className="mobile-nav-backdrop" aria-label="Close navigation overlay" onClick={onClose} />
      <div
        ref={sheetRef}
        className="mobile-nav-sheet scroll-hidden"
        role="dialog"
        aria-modal="true"
        aria-labelledby="mobile-nav-title"
      >
        <div className="mobile-nav-head">
          <p id="mobile-nav-title" className="brand">
            <IconMark />
            <span className="brand-text">
              Job architecture
              <span>Reviewer workspace</span>
            </span>
          </p>
          <button ref={closeRef} type="button" className="icon-btn" aria-label="Close navigation" onClick={onClose}>
            <IconClose />
          </button>
        </div>
        <nav className="nav sidebar-main scroll-hidden" aria-label="Mobile">
          {PRIMARY_LINKS.map((item) => (
            <SidebarNavItem key={item.to} {...item} onNavigate={onClose} />
          ))}
        </nav>
        <div className="sidebar-footer">
          <button type="button" className="nav-item" onClick={onOpenEvidence}>
            <IconDocs />
            <span className="nav-label">Evidence docs</span>
          </button>
        </div>
      </div>
    </div>
  );
}
