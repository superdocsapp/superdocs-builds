import { ArrowRight, CheckCircle2, Download, FileText, Inbox } from "lucide-react";

import { humanizeType } from "./lib/guidance";
import { cleanDetail, formatBytes, formatDate, formatEvent, formatPeriod, formatTimestamp, statusLabel } from "./lib/format";
import type { AuditEvent, CloseDetail, Template } from "./lib/types";

/**
 * The destinations behind the top navigation.
 *
 * Every one of these is built from `GET /api/v1/closes`, which returns each close in full
 * — including its audit trail and export record — so none of them needs a new endpoint.
 * Previously all five nav links merely switched the workspace tab, which is why three of
 * them appeared to do nothing at all.
 */

function EmptyState({ title, detail, children }: { title: string; detail: string; children?: React.ReactNode }) {
  return (
    <div className="empty-state">
      <Inbox size={22} />
      <div>
        <strong>{title}</strong>
        <span>{detail}</span>
      </div>
      {children}
    </div>
  );
}

function PageHeading({ eyebrow, title, lede }: { eyebrow: string; title: string; lede: string }) {
  return (
    <div className="section-heading">
      <div>
        <p className="eyebrow">
          <span /> {eyebrow}
        </p>
        <h2>{title}</h2>
        <p className="page-lede">{lede}</p>
      </div>
    </div>
  );
}

export function ClosesPage({
  closes,
  activeCloseId,
  onOpen
}: {
  closes: CloseDetail[];
  activeCloseId: string | null;
  onOpen: (closeId: string) => void;
}) {
  return (
    <div className="panel-flow">
      <PageHeading
        eyebrow="Your closes"
        title="Every close you are working on"
        lede="Pick a period to open its workspace."
      />
      {closes.length === 0 ? (
        <EmptyState title="No closes yet" detail="When a close period is created it will appear here." />
      ) : (
        <div className="pack-list">
          {closes.map((item) => (
            <button className="data-row button-row" key={item.id} onClick={() => onOpen(item.id)}>
              <FileText size={18} />
              <div>
                <strong>
                  {item.entity} — {formatPeriod(item.period)}
                  {item.id === activeCloseId ? <span className="row-tag">Open</span> : null}
                </strong>
                <span>
                  {statusLabel(item.status)} · {item.readiness?.readiness ?? 0}% ready · due {formatDate(item.due_date)}
                </span>
              </div>
              <ArrowRight size={18} />
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

export function TemplatesPage({ templates, error }: { templates: Template[]; error: string }) {
  return (
    <div className="panel-flow">
      <PageHeading
        eyebrow="Templates"
        title="What a close is built from"
        lede="Each template sets the documents you must collect, the controls you work through, and who signs off."
      />
      {error && <div className="failure-band">{error}</div>}
      {templates.length === 0 && !error ? (
        <EmptyState title="No templates available" detail="Templates define the shape of a close period." />
      ) : (
        <div className="pack-list">
          {templates.map((template) => (
            <div className="template-card" key={template.id}>
              <strong>{template.name}</strong>
              <div className="template-facts">
                <span>
                  <b>{template.required_document_types.length}</b> documents required
                </span>
                <span>
                  <b>{template.checklist_items}</b> checklist controls
                </span>
                <span>
                  <b>{template.signoffs.length}</b> sign-offs
                </span>
              </div>
              <div className="chip-row">
                {template.required_document_types.map((type) => (
                  <span className="chip" key={type}>
                    {humanizeType(type)}
                  </span>
                ))}
              </div>
              <div className="chip-row">
                {template.signoffs.map((role) => (
                  <span className="chip subtle" key={role}>
                    {role}
                  </span>
                ))}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

type FeedEvent = AuditEvent & { closeLabel: string };

export function AuditPage({ closes }: { closes: CloseDetail[] }) {
  // The audit trail ships inside every close, so a cross-close feed is just a merge.
  const events: FeedEvent[] = closes
    .flatMap((item) =>
      (item.audit ?? []).map((event) => ({
        ...event,
        closeLabel: `${item.entity} — ${formatPeriod(item.period)}`
      }))
    )
    .sort((a, b) => (a.created_at < b.created_at ? 1 : -1));

  return (
    <div className="panel-flow">
      <PageHeading
        eyebrow="Activity"
        title="Everything that has happened"
        lede="A complete, attributed record across all of your closes."
      />
      {events.length === 0 ? (
        <EmptyState title="No activity yet" detail="Actions you take in a close are recorded here." />
      ) : (
        <div className="timeline">
          {events.map((event) => {
            const detail = cleanDetail(event.detail);
            return (
              <div className="timeline-row" key={`${event.id}-${event.created_at}`}>
                <CheckCircle2 size={16} />
                <div>
                  <strong>
                    {formatEvent(event.event)}
                    {detail ? ` — ${detail}` : ""}
                  </strong>
                  <span>
                    {event.closeLabel} · {event.actor} · {formatTimestamp(event.created_at)}
                  </span>
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

export function ExportsPage({
  closes,
  busy,
  onOpen,
  onDownload
}: {
  closes: CloseDetail[];
  busy: boolean;
  onOpen: (closeId: string) => void;
  onDownload: (closeId: string) => void;
}) {
  const exported = closes.filter((item) => item.exported && item.export);

  return (
    <div className="panel-flow">
      <PageHeading
        eyebrow="Exports"
        title="Your finished close packs"
        lede="Each pack is the retained record for one period: the evidence, the decisions and the approvals in one file."
      />
      {exported.length === 0 ? (
        <EmptyState
          title="No packs exported yet"
          detail="Once a close is reviewed and signed off, export it and the pack will appear here."
        >
          {closes.length > 0 && (
            <button className="secondary-button" onClick={() => onOpen(closes[0].id)}>
              Open a close
            </button>
          )}
        </EmptyState>
      ) : (
        <div className="pack-list">
          {exported.map((item) => (
            <div className="data-row" key={item.id}>
              <FileText size={18} />
              <div>
                <strong>
                  {item.entity} — {formatPeriod(item.period)}
                </strong>
                <span>
                  {item.export?.filename} · {formatBytes(item.export?.size)} · exported{" "}
                  {formatTimestamp(item.export?.generated_at ?? "")}
                </span>
              </div>
              <button className="secondary-button" disabled={busy} onClick={() => onDownload(item.id)}>
                <Download size={16} /> Download
              </button>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
