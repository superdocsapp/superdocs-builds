import { useState } from "react";
import type { Finding } from "../api";
import { Icon } from "./Icon";
import { DriftDiffPanel } from "./DriftDiffPanel";

interface Props {
  finding: Finding;
  onApprove: (feedback?: string) => Promise<void>;
  onReject: (feedback: string) => Promise<void>;
  /** Rebuild the document in SuperDocs, from the Review page. */
  onReingest?: () => Promise<void>;
  /** Open the document inline, without a trip to the Documents page. */
  onViewDocument?: () => void;
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

/**
 * Recovery for a finding whose document is gone from SuperDocs.
 *
 * Re-ingest is offered here rather than only on the Documents page because
 * this is where the dead end is discovered — pressing "Retry unapplied" and
 * being told to go elsewhere is a worse answer than the fix itself.
 *
 * It confirms first, and says what it costs. Re-ingesting cannot preserve this
 * finding: SuperDocs mints new random chunk ids on every upload, so the
 * evidence would point at chunks that no longer exist. Silently deleting the
 * card the user is reading would be the surprise; naming it beforehand is not.
 */
function RecoveryActions({
  onReingest,
  onViewDocument,
}: {
  onReingest?: () => Promise<void>;
  onViewDocument?: () => void;
}) {
  const [confirming, setConfirming] = useState(false);
  const [busy, setBusy] = useState(false);

  if (!onReingest && !onViewDocument) return null;

  async function run() {
    if (!onReingest) return;
    setBusy(true);
    try {
      await onReingest();
    } finally {
      setBusy(false);
      setConfirming(false);
    }
  }

  return (
    <div className="recovery-actions">
      {confirming ? (
        <div className="recovery-confirm">
          <p className="recovery-confirm-text">
            Re-ingest rebuilds this document in SuperDocs from its original file. SuperDocs
            assigns new section ids on upload, so this finding&rsquo;s evidence stops matching
            and it will be cleared — re-run analysis afterwards to detect the drift again.
            Edits already applied are kept.
          </p>
          <div className="recovery-buttons">
            <button type="button" className="btn btn-primary" onClick={run} disabled={busy}>
              <Icon name="refresh" size={13} /> {busy ? "Re-ingesting…" : "Re-ingest anyway"}
            </button>
            <button
              type="button"
              className="btn btn-ghost"
              onClick={() => setConfirming(false)}
              disabled={busy}
            >
              Cancel
            </button>
          </div>
        </div>
      ) : (
        <div className="recovery-buttons">
          {onReingest && (
            <button
              type="button"
              className="btn btn-primary"
              onClick={() => setConfirming(true)}
              title="Rebuild this document in SuperDocs so fixes can be applied to it again"
            >
              <Icon name="refresh" size={13} /> Re-ingest document
            </button>
          )}
          {onViewDocument && (
            <button
              type="button"
              className="btn btn-ghost btn-icon"
              onClick={onViewDocument}
              title="View this document without leaving Review"
              aria-label="View document"
            >
              <Icon name="eye" size={15} />
            </button>
          )}
        </div>
      )}
    </div>
  );
}

export function FindingCard({
  finding,
  onApprove,
  onReject,
  onReingest,
  onViewDocument,
}: Props) {
  const [showFeedback, setShowFeedback] = useState(false);
  const [feedback, setFeedback] = useState("");
  const [comparing, setComparing] = useState(false);

  if (finding.review_decision) {
    const documentMissing = finding.apply_status === "document_missing";
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
          {documentMissing && (
            <RecoveryActions onReingest={onReingest} onViewDocument={onViewDocument} />
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