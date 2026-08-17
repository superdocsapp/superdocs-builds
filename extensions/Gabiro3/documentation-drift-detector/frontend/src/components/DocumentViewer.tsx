import { useEffect, useRef, useState } from "react";
import {
  getDocumentChunks,
  getDocumentHistory,
  type DocumentChunk,
  type DocumentEdit,
  type DocumentHistory,
  type PendingEdit,
} from "../api";
import { Icon } from "./Icon";

function errorMessage(err: unknown): string {
  return err instanceof Error ? err.message : String(err);
}

function stripTags(html: string | null): string {
  if (!html) return "";
  return html
    .replace(/<[^>]+>/g, " ")
    .replace(/&nbsp;/g, " ")
    .replace(/&amp;/g, "&")
    .replace(/&lt;/g, "<")
    .replace(/&gt;/g, ">")
    .replace(/&quot;/g, '"')
    .replace(/\s+/g, " ")
    .trim();
}

/**
 * Show a chunk's text with the changed span marked.
 *
 * The mark is driven by the substring the fix actually named, so the
 * highlight reflects the recorded edit rather than a diff guessed after the
 * fact. When that substring is not present — a reworded fix, or text SuperDocs
 * normalised — the text is shown plain instead of highlighting something
 * arbitrary.
 */
function ChunkText({ html, mark, tone }: { html: string | null; mark: string | null; tone: "old" | "new" }) {
  const text = stripTags(html);
  if (!text) return <p className="text-muted history-empty-side">(empty)</p>;

  const needle = (mark || "").trim();
  const index = needle ? text.indexOf(needle) : -1;
  if (index === -1) {
    return <p className="history-chunk-text">{text}</p>;
  }

  return (
    <p className="history-chunk-text">
      {text.slice(0, index)}
      <mark className={`diff-highlight diff-highlight-${tone}`}>
        {text.slice(index, index + needle.length)}
      </mark>
      {text.slice(index + needle.length)}
    </p>
  );
}

function EditEntry({ edit, onJump }: { edit: DocumentEdit; onJump: (chunkId: string) => void }) {
  const [open, setOpen] = useState(false);
  const when = edit.applied_at ? new Date(edit.applied_at).toLocaleString() : "unknown time";

  return (
    <li className="history-entry">
      <button type="button" className="history-entry-head" onClick={() => setOpen((v) => !v)}>
        <span className="history-entry-marker" aria-hidden="true" />
        <span className="history-entry-summary">
          <span className="history-entry-title">
            {edit.proposed_old && edit.proposed_new ? (
              <>
                <span className="history-old">{edit.proposed_old}</span>
                <Icon name="chevron-right" size={12} />
                <span className="history-new">{edit.proposed_new}</span>
              </>
            ) : (
              "Edit applied"
            )}
          </span>
          <span className="history-entry-meta">
            {when}
            {edit.review_decision ? ` · ${edit.review_decision}` : ""}
          </span>
        </span>
        <Icon name={open ? "chevron-up" : "chevron-down"} size={14} />
      </button>

      {open && (
        <div className="history-entry-body">
          {edit.ai_explanation && <p className="history-reason">{edit.ai_explanation}</p>}
          {edit.review_feedback && (
            <p className="history-reason text-muted">Reviewer note: {edit.review_feedback}</p>
          )}

          <div className="history-diff">
            <div className="history-diff-side">
              <span className="badge badge-danger">Before</span>
              <ChunkText html={edit.before_html} mark={edit.proposed_old} tone="old" />
            </div>
            <div className="history-diff-side">
              <span className="badge badge-success">After</span>
              <ChunkText html={edit.after_html} mark={edit.proposed_new} tone="new" />
            </div>
          </div>

          <div className="history-entry-footer">
            <p className="history-provenance text-muted">
              Verified byte-identical outside the edited section.
              {edit.superdocs_job_id ? ` SuperDocs job ${edit.superdocs_job_id.slice(0, 12)}` : ""}
            </p>
            {edit.chunk_id && (
              <button type="button" className="btn btn-ghost" onClick={() => onJump(edit.chunk_id!)}>
                <Icon name="eye" size={13} /> Show in document
              </button>
            )}
          </div>
        </div>
      )}
    </li>
  );
}

const PENDING_LABEL: Record<string, string> = {
  queued: "Queued — waiting to be applied",
  applying: "Applying now…",
  blocked: "Blocked by the byte Judge — nothing was changed",
  failed: "Failed — nothing was changed",
};

function PendingEntry({ item }: { item: PendingEdit }) {
  const status = item.apply_status || "queued";
  const tone = status === "blocked" || status === "failed" ? "danger" : "muted";

  return (
    <li className={`history-entry history-entry-${tone}`}>
      <div className="history-entry-head history-entry-head-static">
        <span className="history-entry-marker" aria-hidden="true" />
        <span className="history-entry-summary">
          <span className="history-entry-title">
            {item.proposed_old && item.proposed_new ? (
              <>
                <span className="history-old">{item.proposed_old}</span>
                <Icon name="chevron-right" size={12} />
                <span className="history-new">{item.proposed_new}</span>
              </>
            ) : (
              "Approved fix"
            )}
          </span>
          <span className="history-entry-meta">
            {PENDING_LABEL[status] || status}
            {item.apply_reason ? ` · ${item.apply_reason}` : ""}
          </span>
        </span>
      </div>
    </li>
  );
}

export function DocumentViewer({
  documentId,
  filename,
  targetChunkId,
  onClose,
}: {
  documentId: string;
  filename: string;
  /** Open scrolled to this chunk — how a search result lands on its match. */
  targetChunkId?: string | null;
  onClose: () => void;
}) {
  const [tab, setTab] = useState<"content" | "history">("content");
  const [chunks, setChunks] = useState<DocumentChunk[] | null>(null);
  const [history, setHistory] = useState<DocumentHistory | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [focusedChunk, setFocusedChunk] = useState<string | null>(targetChunkId ?? null);
  const bodyRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    let cancelled = false;
    setChunks(null);
    setHistory(null);
    setError(null);

    // Content and history load together so the History tab can show its count
    // immediately rather than after the user clicks across to it.
    Promise.all([getDocumentChunks(documentId), getDocumentHistory(documentId)])
      .then(([doc, hist]) => {
        if (cancelled) return;
        setChunks(doc.chunks);
        setHistory(hist);
      })
      .catch((err) => {
        if (!cancelled) setError(errorMessage(err));
      });

    return () => {
      cancelled = true;
    };
  }, [documentId]);

  useEffect(() => {
    setFocusedChunk(targetChunkId ?? null);
  }, [targetChunkId]);

  // Scroll only once the chunks are on screen: the element does not exist
  // until then, and scrolling a not-yet-rendered target silently does nothing.
  useEffect(() => {
    if (!focusedChunk || !chunks || tab !== "content") return;
    const el = bodyRef.current?.querySelector(`[data-chunk="${CSS.escape(focusedChunk)}"]`);
    el?.scrollIntoView({ block: "center", behavior: "smooth" });
  }, [focusedChunk, chunks, tab]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const edits = history?.edits ?? [];
  const pending = history?.pending ?? [];
  const editedChunks = new Set(edits.map((e) => e.chunk_id).filter(Boolean) as string[]);

  function jumpToChunk(chunkId: string) {
    setTab("content");
    setFocusedChunk(chunkId);
  }

  return (
    <div className="diff-panel-overlay" onClick={onClose}>
      <aside className="diff-panel doc-viewer" onClick={(event) => event.stopPropagation()}>
        <header className="diff-panel-header">
          <div>
            <p className="eyebrow">Document</p>
            <h2 className="diff-panel-title">{filename}</h2>
          </div>
          <button type="button" className="btn btn-ghost btn-icon" onClick={onClose} aria-label="Close">
            <Icon name="close" size={16} />
          </button>
        </header>

        <nav className="doc-viewer-tabs">
          <button
            type="button"
            className={`doc-viewer-tab ${tab === "content" ? "is-active" : ""}`}
            onClick={() => setTab("content")}
          >
            Content
          </button>
          <button
            type="button"
            className={`doc-viewer-tab ${tab === "history" ? "is-active" : ""}`}
            onClick={() => setTab("history")}
          >
            History{edits.length + pending.length > 0 ? ` (${edits.length + pending.length})` : ""}
          </button>
        </nav>

        <div className="doc-viewer-body" ref={bodyRef}>
          {error && <p className="text-danger">{error}</p>}
          {!error && chunks === null && <p className="text-muted">Loading…</p>}

          {!error && chunks !== null && tab === "content" && (
            <>
              {edits.length > 0 && (
                <p className="doc-viewer-note text-muted">
                  Showing the current text, including {edits.length} applied edit
                  {edits.length === 1 ? "" : "s"}.
                </p>
              )}
              <article className="doc-viewer-content">
                {chunks.map((chunk) => (
                  <div
                    key={chunk.chunk_id}
                    data-chunk={chunk.chunk_id}
                    className={[
                      "doc-chunk",
                      focusedChunk === chunk.chunk_id ? "is-focused" : "",
                      editedChunks.has(chunk.chunk_id) ? "is-edited" : "",
                    ]
                      .filter(Boolean)
                      .join(" ")}
                    /* Chunk HTML from SuperDocs, stored by the ingestor — the
                       same markup the standalone document page renders. */
                    dangerouslySetInnerHTML={{ __html: chunk.html }}
                  />
                ))}
              </article>
            </>
          )}

          {!error && chunks !== null && tab === "history" && (
            <>
              {edits.length === 0 && pending.length === 0 && (
                <div className="empty-state">
                  <p className="empty-state-title">No edits yet</p>
                  <p className="text-muted">
                    This document is unchanged since it was ingested. Approving a drift fix on the
                    Review page will apply it here and record it in this list.
                  </p>
                </div>
              )}

              {pending.length > 0 && (
                <>
                  <p className="eyebrow history-group-label">In progress</p>
                  <ul className="history-list">
                    {pending.map((p) => (
                      <PendingEntry key={p.finding_id} item={p} />
                    ))}
                  </ul>
                </>
              )}

              {edits.length > 0 && (
                <>
                  <p className="eyebrow history-group-label">Applied</p>
                  <ul className="history-list">
                    {edits.map((e) => (
                      <EditEntry key={e.id} edit={e} onJump={jumpToChunk} />
                    ))}
                  </ul>
                </>
              )}
            </>
          )}
        </div>
      </aside>
    </div>
  );
}
