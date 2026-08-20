interface ComparisonBlockProps {
    label: string;
    text: string;
}

function ComparisonBlock({ label, text }: ComparisonBlockProps) {
    return (
        <div className="rounded-lg border border-slate-200 p-4">
            <p className="text-xs font-semibold uppercase tracking-wide text-slate-400">
                {label}
            </p>

            <p className="mt-2 text-sm leading-6 text-slate-700">{text}</p>
        </div>
    );
}

export default ComparisonBlock;
