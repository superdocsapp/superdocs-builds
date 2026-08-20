import type { Deviation, FindingDecision } from "../types/redline";

import ClassificationBadge from "./ClassificationBadge";
import ComparisonBlock from "./ComparisonBlock";

interface FindingCardProps {
    finding: Deviation & {
        id?: string;
        decision?: FindingDecision;
    };
    index: number;
    loading?: boolean;
    onDecision?: (decision: "approve" | "reject") => void;
}

function FindingCard({
    finding,
    index,
    loading = false,
    onDecision,
}: FindingCardProps) {
    const decision = finding.decision;

    return (
        <article className="rounded-xl border border-slate-200 bg-white p-6 shadow-sm">
            {/* Header */}
            <div className="flex items-start justify-between gap-4">
                <div>
                    <p className="text-xs font-medium uppercase tracking-wide text-slate-400">
                        Finding {index + 1}
                    </p>

                    <h4 className="mt-1 font-semibold text-slate-900">
                        {finding.section}
                    </h4>
                </div>

                <ClassificationBadge classification={finding.classification} />
            </div>

            {/* Comparison */}
            <div className="mt-5 grid gap-4 lg:grid-cols-2">
                <ComparisonBlock
                    label="Master Agreement"
                    text={finding.master_text}
                />

                <ComparisonBlock
                    label="Dealer Agreement"
                    text={finding.dealer_text}
                />
            </div>

            {/* Reason */}
            <div className="mt-5 rounded-lg bg-slate-50 p-4">
                <p className="text-xs font-semibold uppercase tracking-wide text-slate-400">
                    Reason
                </p>

                <p className="mt-2 text-sm leading-6 text-slate-700">
                    {finding.reason}
                </p>
            </div>

            {/* Counter position */}
            <div className="mt-4 rounded-lg border border-slate-200 p-4">
                <p className="text-xs font-semibold uppercase tracking-wide text-slate-400">
                    Counter-position
                </p>

                <p className="mt-2 text-sm leading-6 text-slate-700">
                    {finding.counter_position}
                </p>
            </div>

            {/* Decision */}
            <div className="mt-5 flex flex-col gap-4 border-t border-slate-200 pt-5 sm:flex-row sm:items-center sm:justify-between">
                <div>
                    <p className="text-xs font-semibold uppercase tracking-wide text-slate-400">
                        Decision
                    </p>

                    <p
                        className={`mt-1 text-sm font-semibold ${
                            decision === "approve"
                                ? "text-emerald-600"
                                : decision === "reject"
                                  ? "text-red-600"
                                  : "text-slate-500"
                        }`}
                    >
                        {decision === "approve" && "✓ Approved"}
                        {decision === "reject" && "✕ Rejected"}
                        {(!decision || decision === "pending") &&
                            "Pending review"}
                    </p>
                </div>

                {(!decision || decision === "pending") && (
                    <div className="flex gap-3">
                        <button
                            type="button"
                            disabled={loading}
                            onClick={() => onDecision?.("reject")}
                            className="rounded-lg border border-red-200 px-4 py-2 text-sm font-medium text-red-700 transition hover:bg-red-50 disabled:cursor-not-allowed disabled:opacity-40"
                        >
                            Reject
                        </button>

                        <button
                            type="button"
                            disabled={loading}
                            onClick={() => onDecision?.("approve")}
                            className="rounded-lg bg-emerald-600 px-4 py-2 text-sm font-medium text-white transition hover:bg-emerald-700 disabled:cursor-not-allowed disabled:opacity-40"
                        >
                            {loading ? "Saving..." : "Approve"}
                        </button>
                    </div>
                )}
            </div>
        </article>
    );
}

export default FindingCard;
