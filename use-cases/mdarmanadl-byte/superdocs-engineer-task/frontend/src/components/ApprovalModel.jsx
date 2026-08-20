import { useState } from "react";
import { approveChange, rejectChange, approveAll } from "../api/approval";

import { getJob } from "../api/jobs";

export default function ApprovalModal({
  open,
  onClose,
  sessionId,
  jobId,
  pendingChanges,
  setResponse,
  setUpdatedDocumentHtml,
  lastPrompt,
}) {
  const [loading, setLoading] = useState(false);
  const [feedback, setFeedback] = useState("");
  // Keep track of changes already decided in this modal
  const [decidedChanges, setDecidedChanges] = useState([]);
  if (!open) {
    return null;
  }

  const refreshJob = async () => {
    const job = await getJob(jobId);

    if (job.result?.response) {
      setResponse(job.result.response);
    }

    if (job.result?.document_changes?.updated_html) {
      setUpdatedDocumentHtml(job.result.document_changes.updated_html);
    }

    return job;
  };

  const markAsDecided = (changeId) => {
    setDecidedChanges((prev) => {
      if (prev.includes(changeId)) {
        return prev;
      }

      return [...prev, changeId];
    });
  };

  const handleApprove = async (changeId) => {
    try {
      setLoading(true);

      await approveChange(sessionId, jobId, changeId);

      markAsDecided(changeId);

      await refreshJob();

      // Don't close here.
      // User still needs to review remaining changes.
    } catch (error) {
      console.error(error);

      alert(error?.response?.data?.detail || "Approval failed.");
    } finally {
      setLoading(false);
    }
  };

  const handleReject = async (changeId) => {
    try {
      setLoading(true);

      await rejectChange(sessionId, jobId, changeId, feedback, lastPrompt);

      markAsDecided(changeId);

      setFeedback("");

      await refreshJob();

      // Don't close here.
    } catch (error) {
      console.error(error);

      alert(error?.response?.data?.detail || "Rejection failed.");
    } finally {
      setLoading(false);
    }
  };

  const handleApproveAll = async () => {
    try {
      setLoading(true);

      // Only send changes that are still pending
      const remainingChanges = pendingChanges.filter(
        (change) => !decidedChanges.includes(change.change_id),
      );

      await approveAll(sessionId, jobId, remainingChanges);

      const job = await refreshJob();

      // Close only after the whole batch is processed
      if (job.status === "completed" || job.status !== "awaiting_approval") {
        onClose();
      }
    } catch (error) {
      console.error(error);

      alert(error?.response?.data?.detail || "Approve all failed.");
    } finally {
      setLoading(false);
    }
  };

  const remainingCount = pendingChanges.filter(
    (change) => !decidedChanges.includes(change.change_id),
  ).length;

  return (
    <div className="modal-overlay">
      <div className="approval-modal">
        {/* Header */}

        <div className="modal-header">
          <div>
            <div className="modal-eyebrow">HUMAN REVIEW</div>

            <h2>Review AI changes</h2>

            <p>Review each proposed change before it reaches your document.</p>
          </div>

          <button className="modal-close" onClick={onClose} disabled={loading}>
            ×
          </button>
        </div>

        {/* Changes */}

        <div className="approval-content">
          {!pendingChanges?.length ? (
            <div className="empty-changes">No pending changes.</div>
          ) : (
            pendingChanges.map((change, index) => {
              const isDecided = decidedChanges.includes(change.change_id);

              return (
                <div
                  className={`change-card ${
                    isDecided ? "change-card-decided" : ""
                  }`}
                  key={change.change_id}
                >
                  <div className="change-header">
                    <div className="change-number">{index + 1}</div>

                    <div className="change-title">
                      <strong>Proposed edit</strong>

                      <span>{change.operation}</span>
                    </div>

                    <div
                      className={isDecided ? "approved-badge" : "pending-badge"}
                    >
                      {isDecided ? "Reviewed" : "Pending"}
                    </div>
                  </div>

                  {/* Diff */}

                  <div className="diff-grid">
                    <div className="diff-box">
                      <div className="diff-label old">BEFORE</div>

                      <div
                        className="diff-content"
                        dangerouslySetInnerHTML={{
                          __html: change.old_html,
                        }}
                      />
                    </div>

                    <div className="diff-arrow">→</div>

                    <div className="diff-box">
                      <div className="diff-label new">AFTER</div>

                      <div
                        className="diff-content"
                        dangerouslySetInnerHTML={{
                          __html: change.new_html,
                        }}
                      />
                    </div>
                  </div>

                  {/* Explanation */}

                  {change.ai_explanation && (
                    <div className="ai-explanation">
                      <div className="explanation-icon">✦</div>

                      <div>
                        <strong>AI explanation</strong>

                        <p>{change.ai_explanation}</p>
                      </div>
                    </div>
                  )}

                  {/* Feedback */}

                  {!isDecided && (
                    <>
                      <textarea
                        className="feedback-input"
                        rows={2}
                        value={feedback}
                        onChange={(e) => setFeedback(e.target.value)}
                        placeholder="Optional feedback for rejection..."
                        disabled={loading}
                      />

                      {/* Actions */}

                      <div className="change-actions">
                        <button
                          className="reject-button"
                          disabled={loading}
                          onClick={() => handleReject(change.change_id)}
                        >
                          Reject
                        </button>

                        <button
                          className="approve-button"
                          disabled={loading}
                          onClick={() => handleApprove(change.change_id)}
                        >
                          Approve
                        </button>
                      </div>
                    </>
                  )}
                </div>
              );
            })
          )}
        </div>

        {/* Footer */}

        {remainingCount > 1 && (
          <div className="modal-footer">
            <button
              className="approve-all-button"
              disabled={loading}
              onClick={handleApproveAll}
            >
              {loading
                ? "Processing..."
                : `Approve all ${remainingCount} remaining changes`}
            </button>
          </div>
        )}

        {/* All individually reviewed */}

        {remainingCount === 0 && (
          <div className="modal-footer">
            <button className="approve-all-button" onClick={onClose}>
              Done
            </button>
          </div>
        )}
      </div>
    </div>
  );
}
