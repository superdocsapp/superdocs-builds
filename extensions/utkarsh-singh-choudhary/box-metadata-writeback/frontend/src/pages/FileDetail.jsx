import { useEffect, useState } from "react";
import { api } from "../api.js";
import { ClassBadge, ConfidenceValue, HoldSeal, Loading, EmptyState } from "../components/bits.jsx";

const FIELD_LABELS = {
  doc_class: "Document class",
  doc_class_confidence: "Class confidence",
  counterparty_name: "Counterparty",
  effective_date: "Effective date",
  expiration_date: "Expiration date",
  contract_value: "Contract value",
  key_terms_summary: "Key terms",
  retention_category: "Retention category",
  companion_document_id: "Companion document",
  normalized: "Normalized",
  extraction_notes: "Extraction notes",
};

function StageIcon({ status }) {
  const glyph = status === "done" ? "✓" : status === "skipped" ? "·" : "!";
  return <span className={`stage-icon ${status}`}>{glyph}</span>;
}

export default function FileDetail({ fileId, onBack, onDecided }) {
  const [detail, setDetail] = useState(null);
  const [history, setHistory] = useState(null);
  const [governance, setGovernance] = useState(null);
  const [err, setErr] = useState(null);
  const [toast, setToast] = useState(null);
  const [busy, setBusy] = useState(false);

  const load = () => {
    api.fileDetail(fileId).then(setDetail).catch((e) => setErr(e.message));
    api.fileHistory(fileId).then((r) => setHistory(r.changes)).catch(() => setHistory([]));
    api.governanceOutcome(fileId).then(setGovernance).catch(() => setGovernance(null));
  };

  useEffect(load, [fileId]);

  const decide = async (reviewId, approve) => {
    setBusy(true);
    try {
      await (approve ? api.approveReview(reviewId) : api.rejectReview(reviewId));
      setToast(approve ? "Field approved and written to Box metadata." : "Field rejected — held out of metadata.");
      load();
      onDecided?.();
    } catch (e) {
      setToast(`Error: ${e.message}`);
    } finally {
      setBusy(false);
      setTimeout(() => setToast(null), 3500);
    }
  };

  if (err) {
    const isMissing = err.includes("unknown file_id") || err.includes("404");
    return (
      <EmptyState
        title={isMissing ? "This file's Box state is gone" : "Couldn't load this file"}
        body={
          isMissing
            ? "This usually means the server restarted since this file was processed and it's running against the in-memory demo Box client — expected in local/demo mode, not something that happens against a real Box tenant. Re-run the demo scenario to get fresh data."
            : err
        }
      />
    );
  }
  if (!detail) return <Loading />;

  const { metadata, governance: gov, pending_reviews: pending, last_run: run } = detail;
  const hasMetadata = metadata && Object.keys(metadata).length > 0;

  return (
    <div>
      <button className="back-link" onClick={onBack}>
        ← Back to documents
      </button>

      <div className="page-header">
        <div>
          <p className="eyebrow">{fileId}</p>
          <h1 className="page-title">{detail.name || fileId}</h1>
        </div>
        {hasMetadata && <ClassBadge docClass={metadata.doc_class} />}
      </div>

      {gov.legal_hold && (
        <div className="gov-banner">
          <HoldSeal />
          <div>
            <h3>Legal hold active</h3>
            <p>
              AI processing is blocked and no metadata was written. Governance labels and legal holds
              are enforced before any SuperDocs call and again inside Box's own metadata-write boundary —
              this file's fields stay exactly as they were.
            </p>
          </div>
        </div>
      )}

      {toast && <div className="toast">{toast}</div>}

      <div className="detail-grid">
        {/* Left: metadata + pipeline */}
        <div>
          <div className="ledger-card" style={{ marginBottom: 18 }}>
            <h2 className="section-title" style={{ color: "var(--ink-on-paper)" }}>
              Box metadata — documentIntelligence
            </h2>
            {hasMetadata ? (
              <table className="meta-table">
                <tbody>
                  {Object.entries(FIELD_LABELS).map(([key, label]) => {
                    const val = metadata[key];
                    if (val === undefined) return null;
                    return (
                      <tr key={key}>
                        <td className="k">{label}</td>
                        <td className="v">
                          {val === null || val === "" ? (
                            <span className="meta-empty">left empty — not stated in source</span>
                          ) : key === "doc_class_confidence" ? (
                            <ConfidenceValue value={val} />
                          ) : (
                            String(val)
                          )}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            ) : (
              <p style={{ color: "#8a8270", fontSize: 13 }}>
                {gov.legal_hold ? "Blocked by legal hold." : "Not processed yet."}
              </p>
            )}
          </div>

          {run && (
            <div className="card">
              <h2 className="section-title">Processing pipeline</h2>
              <div className="stage-list">
                {run.stages.map((s, i) => (
                  <div className="stage" key={s.name}>
                    <div className="stage-idx">{String(i + 1).padStart(2, "0")}</div>
                    <StageIcon status={s.status} />
                    <div className="stage-body">
                      <div className="stage-name">{s.name.replaceAll("_", " ")}</div>
                      {s.detail && <div className="stage-detail">{s.detail}</div>}
                    </div>
                    <div className="stage-meta">
                      {s.operations > 0 && `${s.operations} op · `}
                      {Math.round(s.latency_ms)}ms
                    </div>
                  </div>
                ))}
              </div>
              <div className="pill-row">
                <span className="chip">Total: {Math.round(run.total_latency_ms)}ms</span>
                <span className="chip">{run.total_operations} SuperDocs operation(s)</span>
                <span className="chip">Version {run.version_sha1?.slice(0, 10)}</span>
              </div>
            </div>
          )}
        </div>

        {/* Right: review, governance outcome, audit */}
        <div>
          {pending && pending.length > 0 && (
            <div style={{ marginBottom: 18 }}>
              <h2 className="section-title">Held for human review</h2>
              {pending.map((r) => (
                <div className="review-card" key={r.review_id}>
                  <div className="review-card-head">
                    <div>
                      <div style={{ fontSize: 11, textTransform: "uppercase", letterSpacing: "0.06em", color: "var(--text-faint)" }}>
                        {r.field_name.replaceAll("_", " ")}
                      </div>
                      <div className="review-value">{r.proposed_value}</div>
                    </div>
                    <ConfidenceValue value={r.confidence} />
                  </div>
                  <div className="review-actions">
                    <button className="btn btn-success btn-sm" disabled={busy} onClick={() => decide(r.review_id, true)}>
                      Approve
                    </button>
                    <button className="btn btn-danger btn-sm" disabled={busy} onClick={() => decide(r.review_id, false)}>
                      Reject
                    </button>
                  </div>
                </div>
              ))}
            </div>
          )}

          {governance && (
            <div className="card" style={{ marginBottom: 18 }}>
              <h2 className="section-title">What this drives in Box</h2>
              <table className="meta-table">
                <tbody>
                  <tr>
                    <td className="k">Disposition eligible</td>
                    <td className="v">{governance.disposition_eligible_now ? "Yes" : "No"}</td>
                  </tr>
                  {governance.disposition_eligible_on && (
                    <tr>
                      <td className="k">Eligible on</td>
                      <td className="v">{governance.disposition_eligible_on}</td>
                    </tr>
                  )}
                  {Object.entries(governance.search_facets || {}).map(([k, v]) => (
                    <tr key={k}>
                      <td className="k">Facet · {k}</td>
                      <td className="v">{v}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              {governance.workflows_triggered?.length > 0 && (
                <div className="pill-row">
                  {governance.workflows_triggered.map((w) => (
                    <span className="chip on" key={w}>{w}</span>
                  ))}
                </div>
              )}
            </div>
          )}

          <div className="card">
            <h2 className="section-title">Audit trail</h2>
            {!history || history.length === 0 ? (
              <p style={{ color: "var(--text-muted)", fontSize: 13 }}>No metadata changes recorded yet.</p>
            ) : (
              <div className="timeline">
                {history
                  .slice()
                  .reverse()
                  .map((h, i) => (
                    <div className="tl-entry" key={i}>
                      <div className="tl-time">{new Date(h.timestamp * 1000).toLocaleString()}</div>
                      <div className="tl-title">{h.field_name.replaceAll("_", " ")} — {h.reason}</div>
                      <div className="tl-detail">
                        {h.old_value ?? <em>empty</em>}
                        <span className="arrow">→</span>
                        {h.new_value ?? <em>empty</em>}
                      </div>
                    </div>
                  ))}
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
