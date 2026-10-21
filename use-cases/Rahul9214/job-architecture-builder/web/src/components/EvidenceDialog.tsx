import { useEffect, useRef, useState } from "react";
import { api } from "../api";
import type { SuperDocsStatus } from "../types";
import { useDialogA11y } from "../hooks/useDialogA11y";
import { IconClose } from "./icons";

const EVIDENCE_DOCS = [
  { path: "TASK2.md", note: "Assigned Task 2 specification" },
  { path: "docs/assignment-audit.md", note: "Requirement-by-requirement coverage" },
  { path: "docs/live-verification.md", note: "Live SuperDocs verification record" },
  { path: "docs/manual-acceptance.md", note: "Manual reviewer acceptance" },
];

export function EvidenceDialog({ open, onClose }: { open: boolean; onClose: () => void }) {
  const rootRef = useRef<HTMLElement>(null);
  const closeRef = useRef<HTMLButtonElement>(null);
  const [status, setStatus] = useState<SuperDocsStatus | null>(null);
  useDialogA11y(open, onClose, rootRef, closeRef);

  useEffect(() => {
    if (!open) return;
    void api
      .superdocs()
      .then(setStatus)
      .catch(() => setStatus(null));
  }, [open]);

  if (!open) return null;

  return (
    <div className="dialog-layer" role="presentation">
      <button type="button" className="backdrop" aria-label="Close evidence docs" onClick={onClose} />
      <aside
        ref={rootRef}
        className="drawer evidence-drawer"
        role="dialog"
        aria-modal="true"
        aria-labelledby="evidence-title"
      >
        <div className="drawer-head">
          <h2 id="evidence-title">Evidence docs</h2>
          <button ref={closeRef} type="button" className="icon-btn" aria-label="Close evidence docs" onClick={onClose}>
            <IconClose />
          </button>
        </div>
        <div className="drawer-body scroll-hidden">
          <p>
            Assignment and verification records live in this repository. They are not hosted product pages. SuperDocs
            live export is a CLI operation; Export shows whether this server is configured.
          </p>
          <p>
            SuperDocs:{" "}
            <span className={`chip ${status?.configured ? "good" : "warn"}`}>
              {status?.configured ? "configured" : "not configured"}
            </span>
          </p>
          <ul className="evidence-list">
            {EVIDENCE_DOCS.map((item) => (
              <li key={item.path}>
                <code>{item.path}</code>
                <span>{item.note}</span>
              </li>
            ))}
          </ul>
        </div>
      </aside>
    </div>
  );
}
