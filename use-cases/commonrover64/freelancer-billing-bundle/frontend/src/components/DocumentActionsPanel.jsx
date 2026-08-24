import { useState } from "react";
import { useDocumentGeneration } from "../hooks/useDocumentGeneration.js";
import ReviewItem from "./ReviewItem.jsx";
import DocumentModal from "./DocumentModal.jsx";

const DOCUMENT_TYPES = [
    {
        key: "engagement-letter",
        label: "Engagement Letter",
        blurb: "Create engagement letter",
    },
    { key: "timesheet", label: "Timesheet", blurb: "Generate timesheet" },
    { key: "invoice", label: "Invoice", blurb: "Create invoice" },
    {
        key: "payment-reminder",
        label: "Payment Reminder",
        blurb: "Send payment reminder",
    },
];

function DocumentActionsPanel({ engagementId, engagementTitle, clientName }) {
    const {
        docState,
        activeType,
        setActiveType,
        localDecisions,
        loading,
        active,
        handleGenerate,
        markDecision,
        handleSubmitReview,
    } = useDocumentGeneration({ engagementId, engagementTitle, clientName });

    const [modalOpen, setModalOpen] = useState(false);

    if (!engagementId) {
        return (
            <div className="card" style={{ width: 280 }}>
                <h2>Generate Documents</h2>
                <p style={{ fontStyle: "italic" }}>
                    Select an engagement first.
                </p>
            </div>
        );
    }

    function openType(type) {
        setActiveType(type);
        setModalOpen(true);
    }

    const activeLabel =
        activeType && DOCUMENT_TYPES.find((d) => d.key === activeType)?.label;

    return (
        <div className="card" style={{ width: 280 }}>
            <h2>Generate Documents</h2>

            {DOCUMENT_TYPES.map((doc) => {
                const state = docState[doc.key];
                return (
                    <button
                        key={doc.key}
                        className="btn btn-coral doc-action-btn"
                        onClick={() => openType(doc.key)}
                    >
                        <div style={{ fontWeight: 700 }}>
                            {doc.label} {state?.status === "completed" && "✓"}
                        </div>
                        <div style={{ fontSize: "0.8rem", fontWeight: 400 }}>
                            {doc.blurb}
                        </div>
                    </button>
                );
            })}

            {modalOpen && (
                <DocumentModal
                    title={activeLabel}
                    onClose={() => setModalOpen(false)}
                >
                    {active?.error && (
                        <p style={{ color: "var(--coral)", fontWeight: 700 }}>
                            {active.error}
                        </p>
                    )}

                    {!active && (
                        <div>
                            <button
                                className="btn btn-teal"
                                onClick={() => handleGenerate(activeType)}
                                disabled={loading}
                            >
                                Generate {activeLabel}
                            </button>
                        </div>
                    )}

                    {active?.status === "generating" && (
                        <p style={{ fontWeight: 700 }}>Working on it...</p>
                    )}

                    {active?.status === "completed" && (
                        <div>
                            <p style={{ fontWeight: 700 }}>
                                {active.hadRejection
                                    ? "Some fields were rejected and remain blank in the document."
                                    : "Generated successfully."}
                            </p>
                            <a
                                href={active.downloadUrl}
                                download={`${activeType}.docx`}
                                className="btn btn-teal"
                                style={{ marginRight: "0.5rem" }}
                            >
                                Download
                            </a>
                            <button
                                className="btn"
                                onClick={() => handleGenerate(activeType)}
                                disabled={loading}
                            >
                                Regenerate
                            </button>
                            {loading && (
                                <p style={{ fontWeight: 700 }}>
                                    Working on it...
                                </p>
                            )}
                        </div>
                    )}

                    {active?.status === "failed" && (
                        <div>
                            <button
                                className="btn btn-coral"
                                onClick={() => handleGenerate(activeType)}
                                disabled={loading}
                            >
                                Retry {activeLabel}
                            </button>
                            {loading && (
                                <p style={{ fontWeight: 700 }}>
                                    Working on it...
                                </p>
                            )}
                        </div>
                    )}

                    {active?.status === "in_review" &&
                        active.pendingChanges.length > 0 && (
                            <div>
                                {active.pendingChanges.map((change) => (
                                    <ReviewItem
                                        key={change.change_id}
                                        change={change}
                                        decision={
                                            localDecisions[change.change_id]
                                        }
                                        onApprove={() =>
                                            markDecision(change.change_id, true)
                                        }
                                        onReject={() =>
                                            markDecision(
                                                change.change_id,
                                                false,
                                            )
                                        }
                                        disabled={loading}
                                    />
                                ))}

                                {active.pendingChanges.every(
                                    (c) =>
                                        localDecisions[c.change_id] ===
                                        undefined,
                                ) && (
                                    <p style={{ fontStyle: "italic" }}>
                                        Every item needs a decision before you
                                        can submit.
                                    </p>
                                )}

                                {(() => {
                                    const decidedCount =
                                        active.pendingChanges.filter(
                                            (c) =>
                                                localDecisions[c.change_id] !==
                                                undefined,
                                        ).length;
                                    const totalCount =
                                        active.pendingChanges.length;
                                    const allDecided =
                                        decidedCount === totalCount;
                                    return (
                                        <>
                                            <p style={{ fontWeight: 700 }}>
                                                {decidedCount} of {totalCount}{" "}
                                                decided
                                            </p>
                                            <button
                                                className="btn btn-coral"
                                                onClick={handleSubmitReview}
                                                disabled={
                                                    loading || !allDecided
                                                }
                                                style={{
                                                    opacity: allDecided
                                                        ? 1
                                                        : 0.5,
                                                }}
                                            >
                                                Submit Review
                                            </button>
                                            {loading && (
                                                <p style={{ fontWeight: 700 }}>
                                                    Working on it...
                                                </p>
                                            )}
                                        </>
                                    );
                                })()}
                            </div>
                        )}
                </DocumentModal>
            )}
        </div>
    );
}

export default DocumentActionsPanel;
