import { useDocumentGeneration } from "../hooks/useDocumentGeneration.js";
import ReviewItem from "./ReviewItem.jsx";

const DOCUMENT_TYPES = [
    { key: "engagement-letter", label: "Engagement Letter" },
    { key: "timesheet", label: "Timesheet" },
    { key: "invoice", label: "Invoice" },
    { key: "payment-reminder", label: "Payment Reminder" },
];

function DocumentGenerator({ engagementId, engagementTitle, clientName }) {
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

    const activeLabel =
        activeType && DOCUMENT_TYPES.find((d) => d.key === activeType)?.label;

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
                            className={`btn btn-coral ${isActive ? "tab-active" : ""}`}
                            onClick={() => setActiveType(doc.key)}
                            disabled={loading}
                        >
                            {doc.label}
                            {state?.status === "completed" && " ✓"}
                        </button>
                    );
                })}
            </div>

            {active?.error && (
                <p
                    style={{
                        color: "var(--coral)",
                        fontWeight: 700,
                        marginTop: "1rem",
                    }}
                >
                    {active.error}
                </p>
            )}

            {activeType && !active && (
                <div style={{ marginTop: "1.5rem" }}>
                    <button
                        className="btn btn-teal"
                        onClick={() => handleGenerate(activeType)}
                        disabled={loading}
                    >
                        Generate {activeLabel}
                    </button>
                    {loading && (
                        <p style={{ fontWeight: 700, marginTop: "0.5rem" }}>
                            Working on it...
                        </p>
                    )}
                </div>
            )}

            {activeType && active?.status === "completed" && (
                <div style={{ marginTop: "1.5rem" }}>
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
                        <p style={{ fontWeight: 700, marginTop: "0.5rem" }}>
                            Working on it...
                        </p>
                    )}
                </div>
            )}

            {activeType && active?.status === "failed" && (
                <div style={{ marginTop: "1.5rem" }}>
                    <button
                        className="btn btn-coral"
                        onClick={() => handleGenerate(activeType)}
                        disabled={loading}
                    >
                        Retry {activeLabel}
                    </button>
                    {loading && (
                        <p style={{ fontWeight: 700, marginTop: "0.5rem" }}>
                            Working on it...
                        </p>
                    )}
                </div>
            )}

            {activeType &&
                active?.status === "in_review" &&
                active.pendingChanges.length > 0 && (
                    <div style={{ marginTop: "1.5rem" }}>
                        <h3>Review changes for {activeType}</h3>

                        {active.pendingChanges.map((change) => (
                            <ReviewItem
                                key={change.change_id}
                                change={change}
                                decision={localDecisions[change.change_id]}
                                onApprove={() =>
                                    markDecision(change.change_id, true)
                                }
                                onReject={() =>
                                    markDecision(change.change_id, false)
                                }
                                disabled={loading}
                            />
                        ))}

                        {active.pendingChanges.every(
                            (c) => localDecisions[c.change_id] === undefined,
                        ) && (
                            <p style={{ fontStyle: "italic" }}>
                                Every item needs a decision before you can
                                submit.
                            </p>
                        )}

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
                                    {loading && (
                                        <p
                                            style={{
                                                fontWeight: 700,
                                                marginTop: "0.5rem",
                                            }}
                                        >
                                            Working on it...
                                        </p>
                                    )}
                                </>
                            );
                        })()}
                    </div>
                )}
        </div>
    );
}

export default DocumentGenerator;
