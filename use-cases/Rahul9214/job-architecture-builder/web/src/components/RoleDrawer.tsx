import { useRef } from "react";
import type { RoleDetail } from "../types";
import { useDialogA11y } from "../hooks/useDialogA11y";
import { FitChip } from "./Status";

export function RoleDrawer({
  role,
  onClose,
}: {
  role: RoleDetail;
  onClose: () => void;
}) {
  const rootRef = useRef<HTMLElement>(null);
  const closeRef = useRef<HTMLButtonElement>(null);
  useDialogA11y(true, onClose, rootRef, closeRef);

  return (
    <>
      <button type="button" className="backdrop" aria-label="Close role evidence" onClick={onClose} />
      <aside ref={rootRef} className="drawer" role="dialog" aria-modal="true" aria-labelledby="role-drawer-title">
        <div className="drawer-head">
          <h2 id="role-drawer-title">{role.title}</h2>
          <button ref={closeRef} type="button" className="ghost" onClick={onClose}>
            Close
          </button>
        </div>
        <div className="drawer-body scroll-hidden">
          <p className="meta-line">{role.team}</p>
          <div className="actions">
            <FitChip status={role.fit_status} />
            <span className="chip">{role.proposed_family ?? "unassigned family"}</span>
            <span className="chip">{role.career_track ?? "no track"}</span>
            <span className="chip">{role.level ?? "no level"}</span>
            <span className="chip">confidence {role.confidence.toFixed(1)}</span>
          </div>
          {role.title_conflict ? (
            <div className="title-vs-evidence">
              <h3>Title vs evidence</h3>
              <dl className="def-list">
                <div>
                  <dt>Title signal</dt>
                  <dd>{role.title_conflict.title_signal}.</dd>
                </div>
                <div>
                  <dt>Evidence-based outcome</dt>
                  <dd>{role.title_conflict.evidence_result}.</dd>
                </div>
                <div>
                  <dt>Why it differs</dt>
                  <dd>
                    {role.title_conflict.summary} The title was not used to classify this role.
                  </dd>
                </div>
              </dl>
            </div>
          ) : null}
          <h3>Supporting evidence</h3>
          <ul>
            {role.supporting_evidence.map((item) => (
              <li key={item}>{item}</li>
            ))}
          </ul>
          <h3>Counter-evidence</h3>
          {role.counter_evidence.length ? (
            <ul>
              {role.counter_evidence.map((item) => (
                <li key={item}>{item}</li>
              ))}
            </ul>
          ) : (
            <p>None recorded.</p>
          )}
          <h3>Evidence signals</h3>
          {Object.entries(role.signals).map(([key, value]) => (
            <p key={key}>
              <strong>{key.replace(/_/g, " ")}.</strong> {value}
            </p>
          ))}
          <div className="evidence-meta">
            <h3>Evidence metadata</h3>
            {role.filename ? <p className="meta-line">Source file: {role.filename}</p> : null}
            <ul>
              {role.source_references.map((item) => (
                <li key={`${item.document_id}-${item.locator}`} className="meta-line">
                  {item.document_id} · {item.locator}
                  {item.excerpt ? ` — ${item.excerpt}` : ""}
                </li>
              ))}
            </ul>
          </div>
        </div>
      </aside>
    </>
  );
}
