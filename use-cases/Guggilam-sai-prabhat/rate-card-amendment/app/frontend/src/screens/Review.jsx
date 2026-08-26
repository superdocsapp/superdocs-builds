import { useEffect, useState } from "react";
import { getReview, submitDecisions, exportCase } from "../api.js";
import StateBadge from "../components/StateBadge.jsx";
import FailureBanner from "../components/FailureBanner.jsx";

export default function Review({ run, caseId, onExported, onBack }) {
  const [review, setReview] = useState(null);
  const [decisions, setDecisions] = useState({});
  const [failure, setFailure] = useState(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    refresh();
  }, [caseId]);

  async function refresh() {
    const fresh = await getReview(run.run_id, caseId);
    setReview(fresh);
    const initial = {};
    fresh.pending_changes.forEach((c) => {
      if (c.decision != null) initial[c.change_id] = c.decision;
    });
    setDecisions(initial);
  }

  function setDecision(changeId, approved) {
    setDecisions((prev) => ({ ...prev, [changeId]: approved }));
  }

  async function handleSubmitDecisions() {
    setFailure(null);
    setBusy(true);
    try {
      const payload = Object.entries(decisions).map(([change_id, approved]) => ({ change_id, approved }));
      const updated = await submitDecisions(run.run_id, caseId, payload);
      setReview(updated);
    } catch (error) {
      setFailure(error.detail || { what: error.message, likely_cause: "unknown", next_action: "retry" });
    } finally {
      setBusy(false);
    }
  }

  function approveAll() {
    const next = {};
    review.pending_changes.forEach((c) => (next[c.change_id] = true));
    setDecisions(next);
  }

  function rejectAll() {
    const next = {};
    review.pending_changes.forEach((c) => (next[c.change_id] = false));
    setDecisions(next);
  }

  async function handleExport() {
    setFailure(null);
    setBusy(true);
    try {
      const result = await exportCase(run.run_id, caseId, "markdown");
      onExported(result);
    } catch (error) {
      setFailure(error.detail || { what: error.message, likely_cause: "unknown", next_action: "retry" });
    } finally {
      setBusy(false);
    }
  }

  if (!review) return <div className="screen">Loading…</div>;

  const allDecided = review.pending_changes.every((c) => decisions[c.change_id] != null);

  return (
    <div className="screen">
      <button className="link-back" onClick={onBack}>
        ← Back to dashboard
      </button>
      <h1>3. Review</h1>
      <div className="review-header">
        <StateBadge state={review.state} />
        <span className="muted">{review.untouched_proof_note}</span>
      </div>
      <FailureBanner failure={failure} />

      {review.instruction_sent && (
        <details className="instruction-box">
          <summary>Instruction sent to SuperDocs</summary>
          <pre>{review.instruction_sent}</pre>
        </details>
      )}

      <h2>Proposed changes</h2>
      {review.pending_changes.length === 0 && <p className="muted">No pending changes.</p>}
      {review.pending_changes.map((change) => (
        <div key={change.change_id} className="change-card">
          <div className="change-columns">
            <div>
              <h3>Exact old content</h3>
              <div
                className="html-preview old"
                dangerouslySetInnerHTML={{ __html: change.old_html || "<em>(new section — nothing to replace)</em>" }}
              />
            </div>
            <div>
              <h3>Exact proposed new content</h3>
              <div className="html-preview new" dangerouslySetInnerHTML={{ __html: change.new_html || "" }} />
            </div>
          </div>
          <p className="muted small">Affected chunk: {change.chunk_id}</p>
          <p className="muted small">{change.ai_explanation}</p>
          <div className="decision-controls">
            <button
              className={decisions[change.change_id] === true ? "active approve" : ""}
              onClick={() => setDecision(change.change_id, true)}
            >
              Approve
            </button>
            <button
              className={decisions[change.change_id] === false ? "active reject" : ""}
              onClick={() => setDecision(change.change_id, false)}
            >
              Reject
            </button>
          </div>
        </div>
      ))}

      {review.pending_changes.length > 0 && (
        <div className="bulk-controls">
          <button onClick={approveAll}>Approve All</button>
          <button onClick={rejectAll}>Reject All</button>
          <button disabled={!allDecided || busy} onClick={handleSubmitDecisions}>
            {busy ? "Submitting…" : "Submit Decisions"}
          </button>
        </div>
      )}

      <h2>Generated amendment letter</h2>
      <pre className="letter-preview">{review.amendment_letter_markdown}</pre>

      {review.state === "approved" && (
        <button className="export-button" disabled={busy} onClick={handleExport}>
          {busy ? "Exporting…" : "Export"}
        </button>
      )}
    </div>
  );
}
