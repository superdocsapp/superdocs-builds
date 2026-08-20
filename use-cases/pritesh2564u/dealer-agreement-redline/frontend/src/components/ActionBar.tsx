interface ActionBarProps {
    reviewStatus: string;
    applying: boolean;
    exporting: boolean;
    onApply: () => void;
    onExport: () => void;
}

function ActionBar({
    reviewStatus,
    applying,
    exporting,
    onApply,
    onExport,
}: ActionBarProps) {
    const canApply = reviewStatus === "completed";

    const canExport = reviewStatus === "applied";

    return (
        <section className="sticky bottom-4 rounded-xl border border-slate-200 bg-white p-4 shadow-lg">
            <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
                <div>
                    <p className="text-sm font-semibold text-slate-900">
                        Review Actions
                    </p>

                    <p className="mt-1 text-xs text-slate-500">
                        {canApply
                            ? "All findings have been reviewed."
                            : canExport
                              ? "Changes have been applied."
                              : "Review all findings before applying changes."}
                    </p>
                </div>

                <div className="flex gap-3">
                    <button
                        type="button"
                        onClick={onApply}
                        disabled={!canApply || applying}
                        className="rounded-lg bg-slate-900 px-5 py-2.5 text-sm font-medium text-white transition hover:bg-slate-700 disabled:cursor-not-allowed disabled:opacity-40"
                    >
                        {applying ? "Applying..." : "Apply Approved Changes"}
                    </button>

                    <button
                        type="button"
                        onClick={onExport}
                        disabled={!canExport || exporting}
                        className="rounded-lg border border-slate-300 bg-white px-5 py-2.5 text-sm font-medium text-slate-700 transition hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-40"
                    >
                        {exporting ? "Exporting..." : "Export DOCX"}
                    </button>
                </div>
            </div>
        </section>
    );
}

export default ActionBar;
