interface SummaryCardProps {
    label: string;
    value: number;
}

function SummaryCard({ label, value }: SummaryCardProps) {
    return (
        <div className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
            <p className="text-sm text-slate-500">{label}</p>

            <p className="mt-2 text-3xl font-semibold text-slate-900">
                {value}
            </p>
        </div>
    );
}

export default SummaryCard;
