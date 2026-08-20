function LoadingState() {
    return (
        <section className="rounded-2xl border border-slate-200 bg-white px-8 py-16 text-center shadow-sm">
            <div className="mx-auto h-8 w-8 animate-spin rounded-full border-4 border-slate-200 border-t-slate-900" />

            <h2 className="mt-5 text-lg font-semibold text-slate-900">
                Analyzing agreement
            </h2>

            <p className="mt-2 text-sm text-slate-500">
                Comparing the dealer agreement against the master agreement and
                playbook.
            </p>
        </section>
    );
}

export default LoadingState;
