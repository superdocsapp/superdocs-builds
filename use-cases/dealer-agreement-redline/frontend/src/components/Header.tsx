interface HeaderProps {
    loading: boolean;
    onStartReview: () => void;
}

function Header({ loading, onStartReview }: HeaderProps) {
    return (
        <header className="border-b border-slate-200 bg-white">
            <div className="mx-auto flex max-w-7xl items-center justify-between px-6 py-5">
                <div>
                    <h1 className="text-2xl font-semibold tracking-tight text-slate-900">
                        Dealer Agreement Redline
                    </h1>

                    <p className="mt-1 text-sm text-slate-500">
                        Review and approve proposed contract changes
                    </p>
                </div>

                <button
                    type="button"
                    onClick={onStartReview}
                    disabled={loading}
                    className="rounded-lg bg-slate-900 px-5 py-2.5 text-sm font-medium text-white transition hover:bg-slate-700 disabled:cursor-not-allowed disabled:opacity-50"
                >
                    {loading ? "Analyzing..." : "Start Review"}
                </button>
            </div>
        </header>
    );
}

export default Header;
