import { useEffect, useRef, useState, type FormEvent } from "react";
import {
  deleteDocument,
  documentContentUrl,
  listDocuments,
  reingestDocument,
  runExistingDocuments,
  uploadDocuments,
  type DocumentSummary,
} from "../api";
import { DocumentViewer } from "../components/DocumentViewer";
import { Icon } from "../components/Icon";
import { RunPicker } from "../components/RunPicker";
import { useRuns } from "../runs/RunContext";
import { useRunActivity } from "../runs/RunActivityContext";
import { useNotifications } from "../notifications/NotificationContext";

function errorMessage(err: unknown): string {
  return err instanceof Error ? err.message : String(err);
}

function UploadForm() {
  const { selectedRunId, refresh, setSelectedRunId } = useRuns();
  const { trackRun } = useRunActivity();
  const { notify } = useNotifications();
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [files, setFiles] = useState<File[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [asNewRun, setAsNewRun] = useState(false);

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    if (files.length === 0) return;
    setBusy(true);
    setError(null);
    try {
      const targetRunId = asNewRun ? undefined : selectedRunId ?? undefined;
      const result = await uploadDocuments(files, targetRunId);
      const label = result.filenames.join(", ");
      notify(
        `${result.filenames.length} file${result.filenames.length === 1 ? "" : "s"} uploaded`,
        `Analyzing… run ${result.run_id.slice(0, 8)}`,
        "info"
      );
      // Watch this run so its completion/failure raises its own toast.
      trackRun(result.run_id, label);
      setFiles([]);
      if (fileInputRef.current) fileInputRef.current.value = "";
      setSelectedRunId(result.run_id);
      refresh();
    } catch (err) {
      const message = errorMessage(err);
      setError(message);
      notify("Upload failed", message, "error");
    } finally {
      setBusy(false);
    }
  }

  return (
    <form className="upload-form card" onSubmit={handleSubmit}>
      <div className="upload-form-row">
        <label className="field upload-field">
          <span className="eyebrow">Files (.md, .html, .txt, .docx, .pdf)</span>
          <input
            ref={fileInputRef}
            type="file"
            multiple
            accept=".md,.html,.htm,.txt,.docx,.pdf,.rtf,.tex"
            onChange={(event) => setFiles(Array.from(event.target.files ?? []))}
          />
        </label>

        <label className="upload-checkbox">
          <input
            type="checkbox"
            checked={asNewRun}
            onChange={(event) => setAsNewRun(event.target.checked)}
          />
          Start a new run
        </label>
      </div>

      {files.length > 0 && (
        <p className="text-muted upload-file-list">
          {files.length} file{files.length > 1 ? "s" : ""}: {files.map((f) => f.name).join(", ")}
        </p>
      )}
      {error && <p className="text-danger">{error}</p>}

      <div className="form-actions">
        <button type="submit" className="btn btn-primary" disabled={busy || files.length === 0}>
          <Icon name="upload" size={14} /> {busy ? "Uploading..." : "Upload"}
        </button>
      </div>
    </form>
  );
}

function DocumentTable({
  documents,
  onDelete,
  onView,
  onReingest,
  reingesting,
  selected,
  onToggle,
  onToggleAll,
}: {
  documents: DocumentSummary[];
  onDelete: (id: string) => void;
  onView: (doc: DocumentSummary) => void;
  onReingest: (doc: DocumentSummary) => void;
  reingesting: string | null;
  selected: Set<string>;
  onToggle: (id: string) => void;
  onToggleAll: () => void;
}) {
  const [confirmId, setConfirmId] = useState<string | null>(null);
  const allSelected = documents.length > 0 && documents.every((d) => selected.has(d.id));

  return (
    <table className="data-table">
      <thead>
        <tr>
          <th className="select-cell">
            <input
              type="checkbox"
              checked={allSelected}
              onChange={onToggleAll}
              aria-label="Select all documents"
            />
          </th>
          <th>Filename</th>
          <th>Sections</th>
          <th>Hash</th>
          <th>Ingested</th>
          <th></th>
        </tr>
      </thead>
      <tbody>
        {documents.map((doc) => (
          <tr key={doc.id} className={selected.has(doc.id) ? "is-selected" : ""}>
            <td className="select-cell">
              <input
                type="checkbox"
                checked={selected.has(doc.id)}
                onChange={() => onToggle(doc.id)}
                aria-label={`Select ${doc.filename}`}
              />
            </td>
            <td className="doc-filename-cell">
              <Icon name="documents" size={14} />
              <span>{doc.filename}</span>
              {/* No durable id means the upload never became a SuperDocs
                  document, so no fix can ever be applied to it. */}
              {!doc.superdocs_doc_id && (
                <span
                  className="badge badge-danger"
                  title="This document was never stored durably in SuperDocs, so fixes cannot be applied to it. Re-ingest to repair."
                >
                  not linked
                </span>
              )}
            </td>
            <td>{doc.chunk_count}</td>
            <td className="mono-cell">{doc.file_hash.slice(0, 12)}...</td>
            <td>{new Date(doc.created_at).toLocaleString()}</td>
            <td>
              <div className="table-row-actions">
                <button
                  className="btn btn-ghost btn-icon"
                  onClick={() => onView(doc)}
                  title="View content and edit history"
                >
                  <Icon name="eye" size={15} />
                </button>
                <a
                  className="btn btn-ghost btn-icon"
                  href={documentContentUrl(doc.id, "attachment", "text")}
                  title="Download as text"
                >
                  <Icon name="download" size={15} />
                </a>
                <button
                  className="btn btn-ghost btn-icon"
                  onClick={() => onReingest(doc)}
                  disabled={reingesting === doc.id}
                  title="Re-ingest from the original file: rebuilds this document in SuperDocs so fixes can be applied to it again"
                >
                  <Icon name="refresh" size={15} />
                </button>
                {confirmId === doc.id ? (
                  <>
                    <button
                      className="btn btn-danger btn-icon"
                      onClick={() => {
                        onDelete(doc.id);
                        setConfirmId(null);
                      }}
                      title="Confirm delete"
                    >
                      <Icon name="check" size={14} />
                    </button>
                    <button
                      className="btn btn-ghost btn-icon"
                      onClick={() => setConfirmId(null)}
                      title="Cancel"
                    >
                      <Icon name="close" size={14} />
                    </button>
                  </>
                ) : (
                  <button
                    className="btn btn-ghost btn-icon"
                    onClick={() => setConfirmId(doc.id)}
                    title="Delete"
                  >
                    <Icon name="trash" size={15} />
                  </button>
                )}
              </div>
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

export function DocumentsPage() {
  const { selectedRunId, setSelectedRunId, refresh } = useRuns();
  const { notify } = useNotifications();
  const [documents, setDocuments] = useState<DocumentSummary[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [viewing, setViewing] = useState<DocumentSummary | null>(null);
  const [reingesting, setReingesting] = useState<string | null>(null);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [analyzing, setAnalyzing] = useState(false);
  const { trackRun, withTask } = useRunActivity();

  const load = () => {
    setLoading(true);
    listDocuments(selectedRunId ?? undefined)
      .then((data) => {
        setDocuments(data.documents);
        setError(null);
      })
      .catch((err) => setError(errorMessage(err)))
      .finally(() => setLoading(false));
  };

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedRunId]);

  function toggle(id: string) {
    setSelected((prev) => {
      const next = new Set(prev);
      next.has(id) ? next.delete(id) : next.add(id);
      return next;
    });
  }

  function toggleAll() {
    setSelected((prev) =>
      prev.size === documents.length ? new Set() : new Set(documents.map((d) => d.id))
    );
  }

  async function handleAnalyzeSelected() {
    const ids = documents.filter((d) => selected.has(d.id)).map((d) => d.id);
    if (ids.length === 0) return;
    const names = documents.filter((d) => selected.has(d.id)).map((d) => d.filename);

    setAnalyzing(true);
    try {
      const res = await withTask("Starting analysis", `${ids.length} document(s)`, () =>
        runExistingDocuments(ids)
      );
      notify(
        "Analysis started",
        `${res.documents} document${res.documents === 1 ? "" : "s"} · run ${res.run_id.slice(0, 8)}` +
          (res.skipped_duplicates
            ? ` · ${res.skipped_duplicates} duplicate file${res.skipped_duplicates === 1 ? "" : "s"} skipped`
            : ""),
        "info"
      );
      trackRun(res.run_id, names.join(", "));
      setSelectedRunId(res.run_id);
      setSelected(new Set());
      refresh();
    } catch (err) {
      const message = errorMessage(err);
      setError(message);
      notify("Could not start analysis", message, "error");
    } finally {
      setAnalyzing(false);
    }
  }

  async function handleDelete(id: string) {
    const doc = documents.find((d) => d.id === id);
    try {
      await withTask("Deleting document", doc?.filename, () => deleteDocument(id));
      setDocuments((docs) => docs.filter((d) => d.id !== id));
      setSelected((prev) => {
        const next = new Set(prev);
        next.delete(id);
        return next;
      });
      notify("Document deleted", doc?.filename, "success");
    } catch (err) {
      const message = errorMessage(err);
      setError(message);
      notify("Delete failed", message, "error");
    }
  }

  async function handleReingest(doc: DocumentSummary) {
    setReingesting(doc.id);
    try {
      const res = await withTask("Re-ingesting document", doc.filename, () =>
        reingestDocument(doc.id)
      );
      notify(
        "Document re-ingested",
        `${res.filename} is linked to SuperDocs again (${res.chunks} sections). ` +
          `Re-run analysis to produce findings against the new sections.`,
        "success"
      );
      load();
    } catch (err) {
      const message = errorMessage(err);
      setError(message);
      notify("Re-ingest failed", message, "error");
    } finally {
      setReingesting(null);
    }
  }

  return (
    <div className="page">
      <header className="page-header page-header-row">
        <div>
          <h1>Documents</h1>
          <p className="page-subtitle">
            Upload, view, download, or delete documents for the selected run. Viewing a document
            shows its current text and every edit applied to it.
          </p>
        </div>
        <RunPicker />
      </header>

      <UploadForm />

      {loading && <p className="text-muted">Loading...</p>}
      {error && <p className="text-danger">{error}</p>}
      {!loading && !error && documents.length === 0 && (
        <div className="empty-state">
          <p className="empty-state-title">No documents yet</p>
          <p className="text-muted">Upload a file above to get started.</p>
        </div>
      )}
      {documents.length > 0 && (
        <>
          <div className="table-toolbar">
            <span className="text-muted table-toolbar-count">
              {selected.size > 0
                ? `${selected.size} selected`
                : `${documents.length} document${documents.length === 1 ? "" : "s"}`}
            </span>
            {/* Analysing what is already ingested needs no upload: SuperDocs
                still holds the documents and we still hold their chunks. */}
            <button
              className="btn btn-primary"
              onClick={handleAnalyzeSelected}
              disabled={selected.size === 0 || analyzing}
              title="Start a new analysis run over the selected documents — nothing is re-uploaded"
            >
              <Icon name="review" size={14} />{" "}
              {analyzing ? "Starting…" : "Analyze selected"}
            </button>
          </div>
          <DocumentTable
            documents={documents}
            onDelete={handleDelete}
            onView={setViewing}
            onReingest={handleReingest}
            reingesting={reingesting}
            selected={selected}
            onToggle={toggle}
            onToggleAll={toggleAll}
          />
        </>
      )}

      {viewing && (
        <DocumentViewer
          documentId={viewing.id}
          filename={viewing.filename}
          onClose={() => setViewing(null)}
        />
      )}
    </div>
  );
}