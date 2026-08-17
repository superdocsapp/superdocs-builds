import { useState } from "react";
import type { Finding } from "../api";
import { Icon } from "./Icon";
import { DriftDiffPanel } from "./DriftDiffPanel";

interface Props {
  finding: Finding;
  onApprove: (feedback?: string) => Promise<void>;
  onReject: (feedback: string) => Promise<void>;
}

/**
 * Approval and application are different events, so they get different
 * badges. "Approved" used to be the end of the story in this UI even when the
 * document had not changed — and even when the apply had been blocked.
 */
function ApplyBadge({ finding }: { finding: Finding }) {
  switch (finding.apply_status) {
    case "applied":
      return (
        <span className="badge badge-success" title={finding.applied_at || undefined}>
          Applied to document
        </span>
      );
    case "applying":
      return <span className="badge badge-neutral">Applying…</span>;
    case "queued":
      return <span className="badge badge-neutral">Queued</span>;
    case "blocked":
      return <span className="badge badge-danger">Blocked — document unchanged</span>;
    case "document_missing":
      // Distinct from a failure: retrying cannot succeed, so the badge points
      // at the action that can.
      return <span className="badge badge-danger">Document missing — re-ingest it</span>;
    case "failed":
      return <span className="badge badge-danger">Apply failed — document unchanged</span>;
    default:
      return <span className="badge badge-neutral">Not applied</span>;
  }
}

export function FindingCard({ finding, onApprove, onReject }: Props) {
  const [showFeedback, setShowFeedback] = useState(false);
  const [feedback, setFeedback] = useState("");
  const [comparing, setComparing] = useState(false);

  if (finding.review_decision) {
    return (
      <div className={`finding-card ${finding.review_decision}`}>
        <div className="finding-card-header">
          <span className="badge">{finding.review_decision.toUpperCase()}</span>
          {finding.review_decision === "approved" && <ApplyBadge finding={finding} />}
        </div>
        <div className="finding-body">
          <p className="filename">{finding.filename || finding.document_id}</p>
          <p className="ai-explanation">{finding.ai_explanation}</p>
          {finding.review_feedback && (
            <p className="feedback">"{finding.review_feedback}"</p>
          )}
          {finding.apply_reason && (
            <p className="text-danger apply-reason">{finding.apply_reason}</p>
          )}
        </div>
      </div>
    );
  }

  return (
    <div className="finding-card pending">
      <div className="finding-card-header">
        <span className="badge">{finding.state}</span>
        <button
          type="button"
          className="btn btn-ghost review-card-compare"
          onClick={() => setComparing(true)}
        >
          <Icon name="compare" size={14} /> Compare
        </button>
      </div>

      {comparing && (
        <DriftDiffPanel
          finding={finding}
          onApprove={onApprove}
          onReject={onReject}
          onClose={() => setComparing(false)}
        />
      )}

      <div className="finding-body">
        <p className="filename">{finding.filename || finding.document_id}</p>
        {finding.evidence_quote && (
          <p className="evidence">
            Evidence: "{finding.evidence_quote}"
          </p>
        )}
        <div className="diff-row">
          <div className="diff-box old">
            <label>Before:</label>
            <code>{finding.proposed_old || "(none)"}</code>
          </div>
          <div className="diff-arrow">&rarr;</div>
          <div className="diff-box new">
            <label>After:</label>
            <code>{finding.proposed_new || "(none)"}</code>
          </div>
        </div>
        {finding.ai_explanation && (
          <p className="ai-explanation">{finding.ai_explanation}</p>
        )}
      </div>
      <div className="finding-actions">
        <button className="btn-approve" onClick={() => onApprove()}>
          Approve
        </button>
        {!showFeedback ? (
          <button
            className="btn-reject"
            onClick={() => setShowFeedback(true)}
          >
            Reject
          </button>
        ) : (
          <div className="feedback-row">
            <input
              value={feedback}
              onChange={(e) => setFeedback(e.target.value)}
              placeholder="Why reject?"
            />
            <button onClick={() => onReject(feedback)}>Submit</button>
            <button onClick={() => setShowFeedback(false)}>Cancel</button>
          </div>
        )}
      </div>
    </div>
  );
}