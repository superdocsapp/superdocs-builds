import type { Deviation, FindingDecision } from "../types/redline";

import FindingCard from "./FindingCard";

interface FindingListProps {
    findings: (Deviation & {
        id?: string;
        decision?: FindingDecision;
    })[];

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
            <div className="mb-4">
                <h3 className="text-lg font-semibold text-slate-900">
                    Findings
                </h3>

                <p className="mt-1 text-sm text-slate-500">
                    Review each proposed deviation before applying changes.
                </p>
            </div>

            <div className="space-y-4">
                {findings.map((finding, index) => (
                    <FindingCard
                        key={finding.id ?? `${finding.section}-${index}`}
                        finding={finding}
                        index={index}
                        loading={processingFindingId === finding.id}
                        onDecision={(decision) => {
                            if (!finding.id) {
                                return;
                            }

                            onDecision(finding.id, decision);
                        }}
                    />
                ))}
            </div>
        </section>
    );
}

export default FindingList;
