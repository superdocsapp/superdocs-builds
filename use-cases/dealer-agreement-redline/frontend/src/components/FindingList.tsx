import type { RedlineFinding } from "../types/redline";

import FindingCard from "./FindingCard";

interface FindingListProps {
    findings: RedlineFinding[];
    processingFindingId?: string | null;
    onDecision: (findingId: string, decision: "approve" | "reject") => void;
}

function FindingList({
    findings,
    processingFindingId,
    onDecision,
}: FindingListProps) {
    return (
        <section>
            <div className="mb-4 flex items-end justify-between">
                <div>
                    <h3 className="text-lg font-semibold text-slate-900">
                        Findings
                    </h3>

                    <p className="mt-1 text-sm text-slate-500">
                        Expand a finding to review its details.
                    </p>
                </div>

                <span className="text-sm text-slate-400">
                    {findings.length}{" "}
                    {findings.length === 1 ? "finding" : "findings"}
                </span>
            </div>

            <div className="space-y-3">
                {findings.map((finding, index) => (
                    <FindingCard
                        key={finding.id}
                        finding={finding}
                        index={index}
                        loading={processingFindingId === finding.id}
                        onDecision={(decision) =>
                            onDecision(finding.id, decision)
                        }
                    />
                ))}
            </div>
        </section>
    );
}

export default FindingList;
