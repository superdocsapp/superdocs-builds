import { useEffect, useMemo, useState } from "react";
import { api } from "../api.js";
import { ClassBadge, ConfidenceValue, ReviewBadge, EmptyState, Loading } from "../components/bits.jsx";

const CLASS_OPTIONS = ["contract", "amendment", "invoice", "policy", "correspondence"];

export default function Documents({ onOpenFile }) {
  const [files, setFiles] = useState(null);
  const [err, setErr] = useState(null);
  const [q, setQ] = useState("");
  const [docClass, setDocClass] = useState(null);
  const [needsReview, setNeedsReview] = useState(false);

  useEffect(() => {
    api.listFiles().then((r) => setFiles(r.files)).catch((e) => setErr(e.message));
  }, []);

  const filtered = useMemo(() => {
    if (!files) return [];
    return files.filter((f) => {
      if (docClass && f.doc_class !== docClass) return false;
      if (needsReview && f.pending_review_count === 0) return false;
      if (q) {
        const hay = `${f.name || ""} ${f.counterparty_name || ""} ${f.file_id}`.toLowerCase();
        if (!hay.includes(q.toLowerCase())) return false;
      }
      return true;
    });
  }, [files, q, docClass, needsReview]);

  if (err) return <EmptyState title="Can't reach the workflow API" body={err} />;
  if (!files) return <Loading />;

  return (
    <div>
      <div className="page-header">
        <div>
          <p className="eyebrow">Documents</p>
          <h1 className="page-title">All files in the workflow</h1>
          <p className="page-sub">Search and filter over live Box metadata — {files.length} file(s) tracked.</p>
        </div>
      </div>

      <div className="filebar">
        <input
          className="search-input"
          placeholder="Search by name or counterparty…"
          value={q}
          onChange={(e) => setQ(e.target.value)}
        />
        {CLASS_OPTIONS.map((c) => (
          <button
            key={c}
            className={`chip ${docClass === c ? "on" : ""}`}
            onClick={() => setDocClass(docClass === c ? null : c)}
          >
            {c}
          </button>
        ))}
        <button className={`chip ${needsReview ? "on" : ""}`} onClick={() => setNeedsReview((v) => !v)}>
          Needs review
        </button>
      </div>

      {filtered.length === 0 ? (
        <EmptyState title="No matching documents" body="Try clearing a filter, or process a new file through the pipeline." />
      ) : (
        <div className="file-list">
          <div className="file-row head">
            <div>Document</div>
            <div>Class</div>
            <div>Counterparty</div>
            <div>Retention</div>
            <div>Confidence</div>
            <div>Status</div>
          </div>
          {filtered.map((f) => (
            <div className="file-row" key={f.file_id} onClick={() => onOpenFile(f.file_id)}>
              <div>
                <div className="file-name">{f.name || f.file_id}</div>
                <span className="file-id">{f.file_id}</span>
              </div>
              <div><ClassBadge docClass={f.doc_class} /></div>
              <div>{f.counterparty_name || <span style={{ color: "var(--text-faint)" }}>—</span>}</div>
              <div className="mono" style={{ fontSize: 12 }}>{f.retention_category || "—"}</div>
              <div><ConfidenceValue value={f.doc_class_confidence} /></div>
              <div>
                {f.legal_hold ? (
                  <span className="badge badge-hold">legal hold</span>
                ) : !f.processed ? (
                  <span className="badge badge-class">not processed</span>
                ) : (
                  <ReviewBadge count={f.pending_review_count} />
                )}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
