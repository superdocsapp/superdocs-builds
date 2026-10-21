import { useState } from "react";
import { ChevronDown, ChevronRight, ScrollText } from "lucide-react";

import { auditDetail, describeAudit, formatTime, type AuditEvent, type WriteBackResult } from "../domain";

/**
 * The append-only record of the run.
 *
 * Every step the server took, in order, with what it was acting on. This is
 * what a reviewer would be asked for if the exported document were ever
 * questioned, so it is part of the product rather than a log file.
 */
export function AuditTrail({
  events,
  checksum,
  writeBack
}: {
  events: AuditEvent[];
  checksum: string | null;
  writeBack: WriteBackResult | null;
}) {
  const [open, setOpen] = useState(false);

  return (
    <section className="panel audit-panel" data-tour="audit">
      <button className="audit-toggle" onClick={() => setOpen((value) => !value)} type="button">
        <span className="panel-icon">
          <ScrollText size={19} />
        </span>
        <div>
          <span className="eyebrow">Audit trail</span>
          <h2>{events.length} recorded {events.length === 1 ? "event" : "events"}</h2>
        </div>
        {open ? <ChevronDown size={16} /> : <ChevronRight size={16} />}
      </button>

      {open && (
        <>
          {(checksum || writeBack) && (
            <div className="audit-meta">
              {checksum && (
                <span>
                  checksum <code>{checksum}</code>
                </span>
              )}
              {writeBack && (
                <span className={writeBack.ok ? "ok" : "bad"}>
                  ServiceNow {writeBack.ok ? "updated" : "update failed"}
                </span>
              )}
            </div>
          )}

          <ol className="audit-list">
            {events.length === 0 && <li className="audit-empty">Nothing has happened yet.</li>}

            {events.map((event, index) => (
              <li key={`${event.at}-${index}`}>
                <span className="audit-time">{formatTime(event.at)}</span>
                <div>
                  <strong>{describeAudit(event)}</strong>
                  {auditDetail(event) && <span>{auditDetail(event)}</span>}
                </div>
              </li>
            ))}
          </ol>
        </>
      )}
    </section>
  );
}
