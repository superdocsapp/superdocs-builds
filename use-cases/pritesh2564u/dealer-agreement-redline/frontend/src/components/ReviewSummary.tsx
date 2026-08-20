import type { ReviewSummary as ReviewSummaryType } from "../types/redline";
import SummaryCard from "./SummaryCard";

interface ReviewSummaryProps {
    summary: ReviewSummaryType;
}

function ReviewSummary({ summary }: ReviewSummaryProps) {
    return (
        <section className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
            <SummaryCard label="Total Findings" value={summary.total} />

            <SummaryCard label="Pre-Approved" value={summary.pre_approved} />

            <SummaryCard label="Escalate" value={summary.escalate} />

            <SummaryCard label="Refuse" value={summary.refuse} />
        </section>
    );
}

export default ReviewSummary;
