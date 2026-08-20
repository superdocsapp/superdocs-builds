interface EmptyStateProps {
    onStartReview: () => void;
}

function EmptyState({ onStartReview }: EmptyStateProps) {
    return (
        <section className="rounded-2xl border border-slate-200 bg-white px-8 py-16 text-center shadow-sm">
            <div className="mx-auto max-w-xl">
                <div className="mx-auto mb-5 flex h-14 w-14 items-center justify-center rounded-full bg-slate-100">
                    <span className="text-2xl">§</span>
                </div>

                <h2 className="text-xl font-semibold text-slate-900">
                    Ready to review the agreement
                </h2>

                <p className="mt-2 text-sm leading-6 text-slate-500">
                    Compare the dealer agreement against the approved master
                    agreement and negotiation playbook.
                </p>

                <button
                    type="button"
                    onClick={onStartReview}
                    className="mt-6 rounded-lg bg-slate-900 px-5 py-2.5 text-sm font-medium text-white transition hover:bg-slate-700"
                >
                    Start Redline Review
                </button>
            </div>
        </section>
    );
}

export default EmptyState;
