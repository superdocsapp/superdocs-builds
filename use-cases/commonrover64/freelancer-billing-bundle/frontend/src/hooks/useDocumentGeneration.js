import { useState } from "react";
import { generateDocument, reviewDocument } from "../services/api.js";

// owns all state and API calls for generating and reviewing documents,
// one entry per document type in docState, so switching types never
// loses progress or leaks another type's error/status.
export function useDocumentGeneration({
    engagementId,
    engagementTitle,
    clientName,
}) {
    const [docState, setDocState] = useState({});
    const [activeType, setActiveType] = useState(null);
    const [localDecisions, setLocalDecisions] = useState({});
    const [loading, setLoading] = useState(false);

    const active = activeType ? docState[activeType] : null;

    async function handleGenerate(type) {
        setLoading(true);
        setLocalDecisions({});

        setDocState((prev) => ({
            ...prev,
            [type]: { status: "generating", pendingChanges: [], error: null },
        }));
        setActiveType(type);

        try {
            const result = await generateDocument(type, engagementId);
            setDocState((prev) => ({
                ...prev,
                [type]: {
                    status: "in_review",
                    jobId: result.jobId,
                    sessionId: result.sessionId,
                    pendingChanges: result.pendingChanges || [],
                    error: null,
                },
            }));
        } catch (err) {
            setDocState((prev) => ({
                ...prev,
                [type]: {
                    status: "failed",
                    pendingChanges: [],
                    error: err.message,
                },
            }));
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
                setDocState((prev) => ({
                    ...prev,
                    [activeType]: {
                        ...prev[activeType],
                        status: "completed",
                        pendingChanges: [],
                        hadRejection,
                        downloadUrl: url,
                        error: null,
                    },
                }));
            } else {
                const data = result.data;

                if (
                    data.status === "failed_needs_manual_retry" ||
                    data.status === "completed_but_incomplete"
                ) {
                    setDocState((prev) => ({
                        ...prev,
                        [activeType]: {
                            ...prev[activeType],
                            status: "failed",
                            pendingChanges: [],
                            error: data.reason,
                        },
                    }));
                } else {
                    setDocState((prev) => ({
                        ...prev,
                        [activeType]: {
                            ...prev[activeType],
                            pendingChanges: data.pendingChanges || [],
                            hadRejection,
                            error: null,
                        },
                    }));
                }
            }
        } catch (err) {
            setDocState((prev) => ({
                ...prev,
                [activeType]: {
                    ...prev[activeType],
                    status: "failed",
                    error: err.message,
                },
            }));
        } finally {
            setLoading(false);
        }
    }

    return {
        docState,
        activeType,
        setActiveType,
        localDecisions,
        loading,
        active,
        handleGenerate,
        markDecision,
        handleSubmitReview,
    };
}
