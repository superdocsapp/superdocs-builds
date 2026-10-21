import { useCallback, useEffect, useId, useRef, useState, type ReactNode } from "react";
import { createPortal } from "react-dom";

export function Tooltip({
  text,
  enabled,
  children,
}: {
  text: string;
  enabled: boolean;
  children: ReactNode;
}) {
  const wrapRef = useRef<HTMLDivElement>(null);
  const tooltipId = useId();
  const [open, setOpen] = useState(false);
  const [pos, setPos] = useState({ top: 0, left: 0 });

  const place = useCallback(() => {
    const node = wrapRef.current;
    if (!node) return;
    const rect = node.getBoundingClientRect();
    const left = Math.min(rect.right + 12, window.innerWidth - 12);
    setPos({ top: rect.top + rect.height / 2, left: Math.max(12, left) });
  }, []);

  const show = useCallback(() => {
    if (!enabled) return;
    place();
    setOpen(true);
  }, [enabled, place]);

  const hide = useCallback(() => setOpen(false), []);

  useEffect(() => {
    if (!enabled) setOpen(false);
  }, [enabled]);

  useEffect(() => {
    if (!open) return;
    function onReposition() {
      place();
    }
    window.addEventListener("resize", onReposition);
    window.addEventListener("scroll", onReposition, true);
    return () => {
      window.removeEventListener("resize", onReposition);
      window.removeEventListener("scroll", onReposition, true);
    };
  }, [open, place]);

  return (
    <div
      ref={wrapRef}
      className="tooltip-wrap"
      onMouseOver={show}
      onMouseOut={(event) => {
        const next = event.relatedTarget as Node | null;
        if (next && wrapRef.current?.contains(next)) return;
        hide();
      }}
      onFocus={show}
      onBlur={hide}
    >
      {children}
      {enabled && open
        ? createPortal(
            <span
              id={tooltipId}
              role="tooltip"
              className="nav-tooltip is-fixed"
              style={{ top: pos.top, left: pos.left }}
            >
              {text}
            </span>,
            document.body,
          )
        : null}
    </div>
  );
}
