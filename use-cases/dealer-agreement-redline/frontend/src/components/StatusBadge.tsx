import type { ReviewStatus } from "../types/redline";

interface StatusBadgeProps {
    status: ReviewStatus;
}

const styles: Record<ReviewStatus, string> = {
    pending: "bg-slate-100 text-slate-600 border-slate-200",

    in_review: "bg-amber-50 text-amber-700 border-amber-200",

    completed: "bg-blue-50 text-blue-700 border-blue-200",

    applied: "bg-emerald-50 text-emerald-700 border-emerald-200",
};

const labels: Record<ReviewStatus, string> = {
    pending: "Pending",
    in_review: "In Review",
    completed: "Ready to Apply",
    applied: "Applied",
};

function StatusBadge({ status }: StatusBadgeProps) {
    return (
        <span
            className={`rounded-full border px-3 py-1 text-xs font-semibold ${styles[status]}`}
        >
            {labels[status]}
        </span>
    );
}

export default StatusBadge;
