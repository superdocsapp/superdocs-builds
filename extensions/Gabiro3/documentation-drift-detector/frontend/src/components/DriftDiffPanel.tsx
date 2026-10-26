import { useEffect, useState } from "react";
import { getDocumentText } from "../api";
import type { Finding } from "../api";
import { Icon } from "./Icon";

function HighlightedText({
  text,
  quote,
  tone,
}: {
  text: string;
  quote: string;
  tone: "old" | "new";
}) {
  if (!quote) {
    return <div className="diff-document-text">{text}</div>;
  }

  const index = text.indexOf(quote);
  if (index === -1) {
    return (
      <div className="diff-doc-wrapper">
        <span className="diff-document-text diff-document-blurred">{text}</span>
        <p className={`diff-quote-fallback diff-quote-${tone}`}>&ldquo;{quote}&rdquo;</p>
      </div>
    );
  }

  const before = text.slice(0, index);
  const match = text.slice(index, index + quote.length);
  const after = text.slice(index + quote.length);

  return (
    <div className="diff-doc-wrapper">
      <div className="diff-document-text">
        <span className="diff-document-blurred">{before}</span>
        <mark className={`diff-highlight diff-highlight-${tone}`}>{match}</mark>
        <span className="diff-document-blurred">{after}</span>
      </div>
    </div>
  );
}

function DocumentColumn({
  documentId,
  quote,
  tone,
}: {
  documentId: string;
  quote: string;
  tone: "old" | "new";
}) {
  const [text, setText] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!documentId) return;
    let cancelled = false;
    getDocumentText(documentId)
      .then((body) => {
        if (!cancelled) setText(body);
      })
      .catch((err) => {
        if (!cancelled) setError(err instanceof Error ? err.message : String(err));
      });
    return () => {
      cancelled = true;
    };
  }, [documentId]);

  if (!documentId) return <p className="text-muted">No source document available.</p>;
  if (error) return <p className="text-danger">{error}</p>;
  if (text === null) return <p className="text-muted">Loading document...</p>;

  return <HighlightedText text={text} quote={quote} tone={tone} />;
}

export function DriftDiffPanel({
  finding,
  onApprove,
  onReject,
  onClose,
}: {
  finding: Finding;
  onApprove: (feedback?: string) => Promise<void>;
  onReject: (feedback: string) => Promise<void>;
  onClose: () => void;
}) {
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const oldQuote = finding.proposed_old || finding.evidence_quote || "";
  const newQuote = finding.proposed_new || "";

  async function handleApprove() {
    setBusy(true);
    setError(null);
    try {
      await onApprove(reason.trim() || undefined);
      onClose();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  async function handleReject() {
    if (!reason.trim()) return;
    setBusy(true);
    setError(null);
    try {
      await onReject(reason.trim());
      onClose();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="diff-panel-overlay" onClick={onClose}>
      <aside className="diff-panel" onClick={(event) => event.stopPropagation()}>
        <header className="diff-panel-header">
          <div>
            <p className="eyebrow">Comparing</p>
            <h2 className="diff-panel-title">{finding.filename || finding.document_id}</h2>
          </div>
          <button type="button" className="btn btn-ghost btn-icon" onClick={onClose} aria-label="Close">
            <Icon name="close" size={16} />
          </button>
        </header>

        <div className="diff-columns">
          <div className="diff-column">
            <div className="diff-column-header">
              <span className="badge badge-danger">Current</span>
            </div>
            <DocumentColumn documentId={finding.document_id} quote={oldQuote} tone="old" />
          </div>

          <div className="diff-column">
            <div className="diff-column-header">
              <span className="badge badge-success">Suggested</span>
            </div>
            <DocumentColumn documentId={finding.document_id} quote={newQuote} tone="new" />
          </div>
        </div>

        <footer className="diff-panel-footer">
          <textarea
            className="review-reason"
            placeholder="Reason (required to reject, optional to approve)"
            value={reason}
            onChange={(event) => setReason(event.target.value)}
          />
          {error && <p className="text-danger">{error}</p>}
          <div className="review-card-actions">
            <button type="button" className="btn btn-primary" disabled={busy} onClick={handleApprove}>
              <Icon name="check" size={14} /> Approve
            </button>
            <button
              type="button"
              className="btn btn-danger"
              disabled={busy || !reason.trim()}
              onClick={handleReject}
            >
              <Icon name="close" size={14} /> Reject
            </button>
            <button type="button" className="btn btn-ghost" onClick={onClose} disabled={busy}>
              Close
            </button>
          </div>
        </footer>
      </aside>
    </div>
  );
}