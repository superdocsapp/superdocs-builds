import { useEffect, useState } from "react";
import { api } from "../api.js";
import { ClassBadge, ConfidenceValue, ReviewBadge, EmptyState, Loading } from "../components/bits.jsx";

function parseMetrics(text) {
  if (!text) return {};
  const out = {};
  for (const line of text.split("\n")) {
    if (line.startsWith("#") || !line.trim()) continue;
    const m = line.match(/^(\w+)(\{.*\})?\s+([\d.]+)$/);
    if (!m) continue;
    const [, name, labels, value] = m;
    if (labels) {
      out[name] = out[name] || {};
      const q = labels.match(/quantile="([\d.]+)"/);
      if (q) out[name][q[1]] = parseFloat(value);
    } else {
      out[name] = parseFloat(value);
    }
  }
  return out;
}

export default function Dashboard({ onOpenFile, onSeedDemo, seeding }) {
  const [files, setFiles] = useState(null);
  const [metrics, setMetrics] = useState({});
  const [err, setErr] = useState(null);

  const load = () => {
    api.listFiles().then((r) => setFiles(r.files)).catch((e) => setErr(e.message));
    api.metrics().then((text) => setMetrics(parseMetrics(text))).catch(() => setMetrics({}));
  };

  useEffect(load, [seeding]);

  if (err) return <EmptyState title="Can't reach the workflow API" body={err} />;
  if (!files) return <Loading />;

  const needsReview = files.filter((f) => f.pending_review_count > 0);
  const held = files.filter((f) => f.legal_hold);

  return (
    <div>
      <div className="page-header">
        <div>
          <p className="eyebrow">Overview</p>
          <h1 className="page-title">Fleet status</h1>
          <p className="page-sub">
            Live counters from the running pipeline — nothing here is sample copy.
          </p>
        </div>
        {files.length === 0 && (
          <button className="btn btn-primary" onClick={onSeedDemo} disabled={seeding}>
            {seeding ? "Seeding…" : "Load Meridian demo scenario"}
          </button>
        )}
      </div>

      <div className="stat-grid">
        <div className="stat-card">
          <div className="stat-num">{metrics.box_workflow_runs_processed_total ?? 0}</div>
          <div className="stat-label">Runs processed</div>
        </div>
        <div className="stat-card">
          <div className="stat-num">{files.length}</div>
          <div className="stat-label">Files tracked</div>
        </div>
        <div className="stat-card">
          <div className="stat-num">{needsReview.length}</div>
          <div className="stat-label">Awaiting review</div>
        </div>
        <div className="stat-card">
          <div className="stat-num">{held.length}</div>
          <div className="stat-label">Under legal hold</div>
        </div>
        <div className="stat-card">
          <div className="stat-num">
            {metrics.box_workflow_run_latency_ms?.["0.95"] != null
              ? `${Math.round(metrics.box_workflow_run_latency_ms["0.95"])}ms`
              : "—"}
          </div>
          <div className="stat-label">p95 run latency</div>
        </div>
        <div className="stat-card">
          <div className="stat-num">{metrics.box_workflow_operations_total ?? 0}</div>
          <div className="stat-label">SuperDocs operations spent</div>
        </div>
      </div>

      {files.length === 0 ? (
        <EmptyState
          title="No files processed yet"
          body="Load the Meridian Cold Chain Logistics demo scenario to see five real documents run through classification, extraction, and metadata write-back — or trigger POST /process/{file_id} against your own seeded files."
        />
      ) : (
        <>
          <h2 className="section-title" style={{ marginTop: 26 }}>
            Files touching governance right now
          </h2>
          <div className="file-list">
            <div className="file-row head">
              <div>Document</div>
              <div>Class</div>
              <div>Counterparty</div>
              <div>Retention</div>
              <div>Confidence</div>
              <div>Review</div>
            </div>
            {files
              .filter((f) => f.pending_review_count > 0 || f.legal_hold)
              .map((f) => (
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
                    ) : (
                      <ReviewBadge count={f.pending_review_count} />
                    )}
                  </div>
                </div>
              ))}
          </div>
        </>
      )}
    </div>
  );
}
