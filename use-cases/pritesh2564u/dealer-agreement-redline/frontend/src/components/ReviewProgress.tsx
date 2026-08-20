interface ReviewProgressProps {
    total: number;
    reviewed: number;
}

function ReviewProgress({ total, reviewed }: ReviewProgressProps) {
    const percentage = total === 0 ? 0 : Math.round((reviewed / total) * 100);

    return (
        <section className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
            <div className="flex items-center justify-between">
                <div>
                    <p className="text-sm font-semibold text-slate-900">
                        Review Progress
                    </p>

                    <p className="mt-1 text-xs text-slate-500">
                        {reviewed} of {total} findings reviewed
                    </p>
                </div>

                <span className="text-sm font-semibold text-slate-700">
                    {percentage}%
                </span>
            </div>

            <div className="mt-4 h-2 overflow-hidden rounded-full bg-slate-100">
                <div
                    className="h-full rounded-full bg-slate-900 transition-all duration-300"
                    style={{
                        width: `${percentage}%`,
                    }}
                />
            </div>
        </section>
    );
}

export default ReviewProgress;
