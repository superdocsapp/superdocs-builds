import { useState } from "react";
import { generateDocument, reviewDocument } from "../services/api.js";

const DOCUMENT_TYPES = [
    { key: "engagement-letter", label: "Engagement Letter" },
    { key: "timesheet", label: "Timesheet" },
    { key: "invoice", label: "Invoice" },
    { key: "payment-reminder", label: "Payment Reminder" },
];

// strips HTML tags for clean display, adding readable separators for table rows/cells
// so a diff like "<tr><td>Date</td>..." doesn't collapse into unreadable run-on text.
function stripHtml(html) {
    return html
        .replace(/<tr[^>]*>/gi, "\n")
        .replace(/<\/?(td|th)[^>]*>/gi, " | ")
        .replace(/<[^>]+>/g, "")
        .replace(/\s+\|\s+/g, " | ")
        .replace(/\n\s*\|\s*/g, "\n")
        .trim();
}

// renders stripped text with line breaks preserved, since JSX collapses \n by default.
function DiffText({ text }) {
    return text.split("\n").map((line, i) => <div key={i}>{line}</div>);
}

function DocumentGenerator({ engagementId, engagementTitle, clientName }) {
    const [docState, setDocState] = useState({});
    const [activeType, setActiveType] = useState(null);
    const [localDecisions, setLocalDecisions] = useState({});
    const [error, setError] = useState(null);
    const [loading, setLoading] = useState(false);

    const active = activeType ? docState[activeType] : null;

    async function handleGenerate(type) {
        setError(null);
        setLoading(true);
        setActiveType(type);
        setLocalDecisions({});

        setDocState((prev) => {
            const next = { ...prev };
            delete next[type];
            return next;
        });

        try {
            const result = await generateDocument(type, engagementId);
            setDocState((prev) => ({
                ...prev,
                [type]: {
                    status: "in_review",
                    jobId: result.jobId,
                    sessionId: result.sessionId,
                    pendingChanges: result.pendingChanges || [],
                },
            }));
        } catch (err) {
            setError(err.message);
        } finally {
            setLoading(false);
        }
    }

    // Marks a local decision only, does not call the API yet. All decisions
    // for the current batch get submitted together via handleSubmitReview.
    function markDecision(changeId, approved) {
        setLocalDecisions((prev) => ({ ...prev, [changeId]: approved }));
    }

    async function handleSubmitReview() {
        setLoading(true);
        setError(null);

        const decisions = active.pendingChanges.map((change) => ({
            change_id: change.change_id,
            approved: localDecisions[change.change_id],
        }));

        const hadRejection =
            decisions.some((d) => !d.approved) || active.hadRejection;

        // These two values should appear in every document type, regardless of
        // which fields were approved or rejected, so we can catch a job that
        // silently skips them.
        const expectedValues = [clientName, engagementTitle].filter(Boolean);

        try {
            const result = await reviewDocument({
                sessionId: active.sessionId,
                jobId: active.jobId,
                decisions,
                expectedValues,
            });

            setLocalDecisions({});

            if (result.isBinary) {
                const url = URL.createObjectURL(result.blob);
                const a = document.createElement("a");
                a.href = url;
                a.download = `${activeType}.docx`;
                a.click();

                setDocState((prev) => ({
                    ...prev,
                    [activeType]: {
                        ...prev[activeType],
                        status: "completed",
                        pendingChanges: [],
                        hadRejection,
                    },
                }));
            } else {
                const data = result.data;

                if (
                    data.status === "failed_needs_manual_retry" ||
                    data.status === "completed_but_incomplete"
                ) {
                    setError(data.reason);
                    setDocState((prev) => ({
                        ...prev,
                        [activeType]: {
                            ...prev[activeType],
                            status: "failed",
                            pendingChanges: [],
                        },
                    }));
                } else {
                    setDocState((prev) => ({
                        ...prev,
                        [activeType]: {
                            ...prev[activeType],
                            pendingChanges: data.pendingChanges || [],
                            hadRejection,
                        },
                    }));
                }
            }
        } catch (err) {
            setError(err.message);
        } finally {
            setLoading(false);
        }
    }

    return (
        <div className="card">
            <h2>Generate Documents</h2>

            <div style={{ display: "flex", gap: "0.75rem", flexWrap: "wrap" }}>
                {DOCUMENT_TYPES.map((doc) => {
                    const state = docState[doc.key];
                    const isActive = activeType === doc.key;

                    return (
                        <button
                            key={doc.key}
                            className="btn btn-coral"
                            style={
                                isActive
                                    ? {
                                          borderColor: "var(--violet)",
                                          borderWidth: "4px",
                                      }
                                    : {}
                            }
                            onClick={() => setActiveType(doc.key)}
                            disabled={loading}
                        >
                            {doc.label}
                            {state?.status === "completed" && " ✓"}
                        </button>
                    );
                })}
            </div>

            {loading && (
                <p style={{ fontWeight: 700, marginTop: "1rem" }}>
                    Working on it...
                </p>
            )}

            {error && (
                <p
                    style={{
                        color: "var(--coral)",
                        fontWeight: 700,
                        marginTop: "1rem",
                    }}
                >
                    {error}
                </p>
            )}

            {activeType && !active && (
                <div style={{ marginTop: "1.5rem" }}>
                    <button
                        className="btn btn-teal"
                        onClick={() => handleGenerate(activeType)}
                        disabled={loading}
                    >
                        Generate{" "}
                        {DOCUMENT_TYPES.find((d) => d.key === activeType).label}
                    </button>
                </div>
            )}

            {activeType && active?.status === "completed" && (
                <div style={{ marginTop: "1.5rem" }}>
                    <p style={{ fontWeight: 700 }}>
                        {active.hadRejection
                            ? "Downloaded, but some fields were rejected and remain blank in the document."
                            : "Generated and downloaded successfully."}
                    </p>
                    <button
                        className="btn"
                        onClick={() => handleGenerate(activeType)}
                        disabled={loading}
                    >
                        Regenerate
                    </button>
                </div>
            )}

            {activeType && active?.status === "failed" && (
                <div style={{ marginTop: "1.5rem" }}>
                    <button
                        className="btn btn-coral"
                        onClick={() => handleGenerate(activeType)}
                        disabled={loading}
                    >
                        Retry{" "}
                        {DOCUMENT_TYPES.find((d) => d.key === activeType).label}
                    </button>
                </div>
            )}

            {activeType &&
                active?.status === "in_review" &&
                active.pendingChanges.length > 0 && (
                    <div style={{ marginTop: "1.5rem" }}>
                        <h3>Review changes for {activeType}</h3>
                        <p style={{ fontStyle: "italic" }}>
                            Every item needs a decision before you can submit.
                        </p>

                        {active.pendingChanges.map((change) => {
                            const decision = localDecisions[change.change_id];

                            return (
                                <div
                                    key={change.change_id}
                                    className="card"
                                    style={{
                                        marginBottom: "1rem",
                                        borderColor:
                                            decision === undefined
                                                ? "var(--ink)"
                                                : "var(--teal)",
                                    }}
                                >
                                    {change.isSuspectedBluff && (
                                        <p
                                            style={{
                                                color: "var(--coral)",
                                                fontWeight: 700,
                                            }}
                                        >
                                            Warning, this looks like a
                                            placeholder, not a real value.
                                        </p>
                                    )}
                                    <div>
                                        <strong>Before:</strong>{" "}
                                        <DiffText
                                            text={stripHtml(change.old_html)}
                                        />
                                    </div>
                                    <div>
                                        <strong>After:</strong>{" "}
                                        <DiffText
                                            text={stripHtml(change.new_html)}
                                        />
                                    </div>
                                    <div
                                        style={{
                                            display: "flex",
                                            gap: "0.5rem",
                                            alignItems: "center",
                                        }}
                                    >
                                        <button
                                            className="btn btn-teal"
                                            style={
                                                decision === true
                                                    ? {
                                                          borderColor:
                                                              "var(--ink)",
                                                          borderWidth: "4px",
                                                      }
                                                    : {}
                                            }
                                            onClick={() =>
                                                markDecision(
                                                    change.change_id,
                                                    true,
                                                )
                                            }
                                            disabled={loading}
                                        >
                                            Approve
                                        </button>
                                        <button
                                            className="btn"
                                            style={
                                                decision === false
                                                    ? {
                                                          borderColor:
                                                              "var(--coral)",
                                                          borderWidth: "4px",
                                                      }
                                                    : {}
                                            }
                                            onClick={() =>
                                                markDecision(
                                                    change.change_id,
                                                    false,
                                                )
                                            }
                                            disabled={loading}
                                        >
                                            Reject
                                        </button>
                                        {decision === undefined && (
                                            <span
                                                style={{
                                                    color: "var(--coral)",
                                                    fontWeight: 700,
                                                }}
                                            >
                                                Needs a decision
                                            </span>
                                        )}
                                    </div>
                                </div>
                            );
                        })}

                        {(() => {
                            const decidedCount = active.pendingChanges.filter(
                                (c) =>
                                    localDecisions[c.change_id] !== undefined,
                            ).length;
                            const totalCount = active.pendingChanges.length;
                            const allDecided = decidedCount === totalCount;

                            return (
                                <>
                                    <p style={{ fontWeight: 700 }}>
                                        {decidedCount} of {totalCount} decided
                                    </p>
                                    <button
                                        className="btn btn-coral"
                                        onClick={handleSubmitReview}
                                        disabled={loading || !allDecided}
                                        style={{
                                            marginTop: "0.5rem",
                                            opacity: allDecided ? 1 : 0.5,
                                        }}
                                    >
                                        Submit Review
                                    </button>
                                </>
                            );
                        })()}
                    </div>
                )}
        </div>
    );
}

export default DocumentGenerator;
