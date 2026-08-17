import { useEffect, useRef, useState, type FormEvent } from "react";
import {
  deleteDocument,
  documentContentUrl,
  listDocuments,
  reingestDocument,
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
}: {
  documents: DocumentSummary[];
  onDelete: (id: string) => void;
  onView: (doc: DocumentSummary) => void;
  onReingest: (doc: DocumentSummary) => void;
  reingesting: string | null;
}) {
  const [confirmId, setConfirmId] = useState<string | null>(null);

  return (
    <table className="data-table">
      <thead>
        <tr>
          <th>Filename</th>
          <th>Sections</th>
          <th>Hash</th>
          <th>Ingested</th>
          <th></th>
        </tr>
      </thead>
      <tbody>
        {documents.map((doc) => (
          <tr key={doc.id}>
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
  const { selectedRunId } = useRuns();
  const { notify } = useNotifications();
  const [documents, setDocuments] = useState<DocumentSummary[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [viewing, setViewing] = useState<DocumentSummary | null>(null);
  const [reingesting, setReingesting] = useState<string | null>(null);

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

  async function handleDelete(id: string) {
    const doc = documents.find((d) => d.id === id);
    try {
      await deleteDocument(id);
      setDocuments((docs) => docs.filter((d) => d.id !== id));
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
      const res = await reingestDocument(doc.id);
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
        <DocumentTable
          documents={documents}
          onDelete={handleDelete}
          onView={setViewing}
          onReingest={handleReingest}
          reingesting={reingesting}
        />
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