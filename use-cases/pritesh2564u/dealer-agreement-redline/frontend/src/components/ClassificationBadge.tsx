import type { Classification } from "../types/redline";

interface ClassificationBadgeProps {
    classification: Classification;
}

const classes: Record<Classification, string> = {
    "PRE-APPROVED": "bg-emerald-50 text-emerald-700 border-emerald-200",

    ESCALATE: "bg-amber-50 text-amber-700 border-amber-200",

    REFUSE: "bg-red-50 text-red-700 border-red-200",
};

function ClassificationBadge({ classification }: ClassificationBadgeProps) {
    return (
        <span
            className={`rounded-full border px-3 py-1 text-xs font-semibold ${classes[classification]}`}
        >
            {classification}
        </span>
    );
}

export default ClassificationBadge;
