import { Check, ChevronDown, ChevronRight, X } from "lucide-react";
import { useState } from "react";

import type { FindingDecision, RedlineFinding } from "../types/redline";

import ClassificationBadge from "./ClassificationBadge";
import ComparisonBlock from "./ComparisonBlock";

interface FindingCardProps {
    finding: RedlineFinding;
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
    const [expanded, setExpanded] = useState(
        index === 0 && finding.decision === "pending",
    );

    const decision: FindingDecision = finding.decision;

    const reviewed = decision !== "pending";

    return (
        <article
            className={`overflow-hidden rounded-xl border bg-white shadow-sm transition ${
                reviewed ? "border-slate-200" : "border-slate-300"
            }`}
        >
            {/* Collapsed header */}
            <button
                type="button"
                onClick={() => setExpanded((current) => !current)}
                className="flex w-full items-center gap-4 px-5 py-4 text-left transition hover:bg-slate-50"
                aria-expanded={expanded}
            >
                <div className="flex shrink-0 items-center text-slate-400">
                    {expanded ? (
                        <ChevronDown size={19} />
                    ) : (
                        <ChevronRight size={19} />
                    )}
                </div>

                <div className="min-w-0 flex-1">
                    <div className="flex flex-wrap items-center gap-2">
                        <span className="text-xs font-medium uppercase tracking-wide text-slate-400">
                            Finding {index + 1}
                        </span>

                        <ClassificationBadge
                            classification={finding.classification}
                        />
                    </div>

                    <h4 className="mt-1 truncate font-semibold text-slate-900">
                        {finding.section}
                    </h4>
                </div>

                <div className="hidden shrink-0 sm:block">
                    {decision === "approve" && (
                        <span className="flex items-center gap-1.5 text-xs font-semibold text-emerald-600">
                            <Check size={15} />
                            Approved
                        </span>
                    )}

                    {decision === "reject" && (
                        <span className="flex items-center gap-1.5 text-xs font-semibold text-red-600">
                            <X size={15} />
                            Rejected
                        </span>
                    )}

                    {decision === "pending" && (
                        <span className="text-xs font-medium text-slate-400">
                            Pending
                        </span>
                    )}
                </div>
            </button>

            {/* Expanded content */}
            {expanded && (
                <div className="border-t border-slate-200 px-5 pb-5 pt-5">
                    <div className="grid gap-4 lg:grid-cols-2">
                        <ComparisonBlock
                            label="Master Agreement"
                            text={finding.master_text}
                        />

                        <ComparisonBlock
                            label="Dealer Agreement"
                            text={finding.dealer_text}
                        />
                    </div>

                    <div className="mt-4 rounded-lg bg-slate-50 p-4">
                        <p className="text-xs font-semibold uppercase tracking-wide text-slate-400">
                            Reason
                        </p>

                        <p className="mt-2 text-sm leading-6 text-slate-700">
                            {finding.reason}
                        </p>
                    </div>

                    <div className="mt-4 rounded-lg border border-slate-200 p-4">
                        <p className="text-xs font-semibold uppercase tracking-wide text-slate-400">
                            Counter-position
                        </p>

                        <p className="mt-2 text-sm leading-6 text-slate-700">
                            {finding.counter_position}
                        </p>
                    </div>

                    {!reviewed && (
                        <div className="mt-5 flex flex-col gap-3 border-t border-slate-200 pt-5 sm:flex-row sm:items-center sm:justify-between">
                            <p className="text-xs text-slate-500">
                                Review this finding before applying changes.
                            </p>

                            <div className="flex gap-3">
                                <button
                                    type="button"
                                    disabled={loading}
                                    onClick={() => onDecision?.("reject")}
                                    className="flex items-center justify-center gap-2 rounded-lg border border-red-200 px-4 py-2 text-sm font-medium text-red-700 transition hover:bg-red-50 disabled:cursor-not-allowed disabled:opacity-40"
                                >
                                    <X size={16} />
                                    Reject
                                </button>

                                <button
                                    type="button"
                                    disabled={loading}
                                    onClick={() => onDecision?.("approve")}
                                    className="flex items-center justify-center gap-2 rounded-lg bg-emerald-600 px-4 py-2 text-sm font-medium text-white transition hover:bg-emerald-700 disabled:cursor-not-allowed disabled:opacity-40"
                                >
                                    <Check size={16} />
                                    {loading ? "Saving..." : "Approve"}
                                </button>
                            </div>
                        </div>
                    )}

                    {reviewed && (
                        <div className="mt-5 border-t border-slate-200 pt-4">
                            <p
                                className={`flex items-center gap-2 text-sm font-semibold ${
                                    decision === "approve"
                                        ? "text-emerald-600"
                                        : "text-red-600"
                                }`}
                            >
                                {decision === "approve" ? (
                                    <>
                                        <Check size={17} />
                                        Finding approved
                                    </>
                                ) : (
                                    <>
                                        <X size={17} />
                                        Finding rejected
                                    </>
                                )}
                            </p>
                        </div>
                    )}
                </div>
            )}
        </article>
    );
}

export default FindingCard;
