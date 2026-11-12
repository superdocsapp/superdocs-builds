import { useState } from "react";

import {
    analyzeRedline,
    applyReview,
    decideFinding,
    exportReview,
    getRedlineReview,
} from "./api/redline";

import type { AnalyzeResponse, RedlineReview } from "./types/redline";

import ActionBar from "./components/ActionBar";
import EmptyState from "./components/EmptyState";
import FindingList from "./components/FindingList";
import Header from "./components/Header";
import LoadingState from "./components/LoadingState";
import ReviewProgress from "./components/ReviewProgress";
import ReviewSummary from "./components/ReviewSummary";
import StatusBadge from "./components/StatusBadge";
import SuccessMessage from "./components/SuccessMessage";

function App() {
    const [analysis, setAnalysis] = useState<AnalyzeResponse | null>(null);

    const [review, setReview] = useState<RedlineReview | null>(null);

    const [loading, setLoading] = useState(false);

    const [processingFindingId, setProcessingFindingId] = useState<
        string | null
    >(null);

    const [applying, setApplying] = useState(false);

    const [exporting, setExporting] = useState(false);

    const [error, setError] = useState<string | null>(null);

    const [success, setSuccess] = useState<string | null>(null);

    async function handleAnalyze(
        dealerFile: File,
        masterFile: File,
        playbookFile: File,
    ) {
        setLoading(true);
        setError(null);
        setSuccess(null);

        try {
            const result = await analyzeRedline(
                dealerFile,
                masterFile,
                playbookFile,
            );

            setAnalysis(result);

            const reviewResult = await getRedlineReview(result.review_id);

            setReview(reviewResult);

            setSuccess("Agreement analysis completed successfully.");
        } catch (err) {
            console.error(err);

            setError(
                err instanceof Error
                    ? err.message
                    : "Failed to analyze the agreement.",
            );
        } finally {
            setLoading(false);
        }
    }

    async function handleDecision(
        findingId: string,
        decision: "approve" | "reject",
    ) {
        if (!review) {
            return;
        }

        setProcessingFindingId(findingId);
        setError(null);
        setSuccess(null);

        try {
            const result = await decideFinding(
                review.review_id,
                findingId,
                decision,
            );

            setReview((current) => {
                if (!current) {
                    return current;
                }

                return {
                    ...current,
                    status: result.review_status,
                    findings: current.findings.map((finding) =>
                        finding.id === findingId
                            ? {
                                  ...finding,
                                  decision: result.decision,
                              }
                            : finding,
                    ),
                };
            });

            setSuccess(
                decision === "approve"
                    ? "Finding approved successfully."
                    : "Finding rejected successfully.",
            );
        } catch (err) {
            console.error(err);

            setError(
                err instanceof Error
                    ? err.message
                    : "Failed to save the finding decision.",
            );
        } finally {
            setProcessingFindingId(null);
        }
    }

    async function handleApply() {
        if (!review) {
            return;
        }

        if (review.status !== "completed") {
            return;
        }

        setApplying(true);
        setError(null);
        setSuccess(null);

        try {
            const result = await applyReview(review.review_id);

            setReview((current) => {
                if (!current) {
                    return current;
                }

                return {
                    ...current,
                    status: result.status,
                };
            });

            setSuccess("Approved changes have been applied successfully.");
        } catch (err) {
            console.error(err);

            setError(
                err instanceof Error
                    ? err.message
                    : "Failed to apply the approved changes.",
            );
        } finally {
            setApplying(false);
        }
    }

    async function handleExport() {
        if (!review) {
            return;
        }

        if (review.status !== "applied") {
            return;
        }

        setExporting(true);
        setError(null);
        setSuccess(null);

        try {
            const blob = await exportReview(review.review_id);

            const url = window.URL.createObjectURL(blob);

            const link = document.createElement("a");

            link.href = url;
            link.download = "dealer-agreement-redlined.docx";

            document.body.appendChild(link);

            link.click();

            link.remove();

            window.URL.revokeObjectURL(url);

            setSuccess("Redlined DOCX exported successfully.");
        } catch (err) {
            console.error(err);

            setError(
                err instanceof Error
                    ? err.message
                    : "Failed to export the document.",
            );
        } finally {
            setExporting(false);
        }
    }

    const reviewedCount =
        review?.findings.filter((finding) => finding.decision !== "pending")
            .length ?? 0;

    return (
        <div className="min-h-screen bg-slate-50">
            <Header />

            <main className="mx-auto max-w-7xl px-6 pb-32 pt-24">
                {success && (
                    <SuccessMessage
                        message={success}
                        onDismiss={() => setSuccess(null)}
                    />
                )}

                {error && (
                    <div className="mb-6 rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
                        {error}
                    </div>
                )}

                {!analysis && !loading && (
                    <EmptyState loading={loading} onAnalyze={handleAnalyze} />
                )}

                {loading && <LoadingState />}

                {analysis && review && !loading && (
                    <div className="space-y-8">
                        <section>
                            <div className="flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
                                <div>
                                    <p className="text-sm font-medium text-slate-500">
                                        Review
                                    </p>

                                    <h2 className="mt-1 text-2xl font-semibold text-slate-900">
                                        Agreement Findings
                                    </h2>
                                </div>

                                <StatusBadge status={review.status} />
                            </div>
                        </section>

                        <ReviewSummary summary={analysis.summary} />

                        <ReviewProgress
                            total={review.findings.length}
                            reviewed={reviewedCount}
                        />

                        <FindingList
                            findings={review.findings}
                            processingFindingId={processingFindingId}
                            onDecision={handleDecision}
                        />

                        <ActionBar
                            reviewStatus={review.status}
                            applying={applying}
                            exporting={exporting}
                            onApply={handleApply}
                            onExport={handleExport}
                        />
                    </div>
                )}
            </main>
        </div>
    );
}

export default App;
