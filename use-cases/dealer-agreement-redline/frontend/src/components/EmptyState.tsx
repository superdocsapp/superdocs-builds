import DocumentUpload from "./DocumentUpload";

interface EmptyStateProps {
    loading: boolean;

    onAnalyze: (dealerFile: File, masterFile: File, playbookFile: File) => void;
}

function EmptyState({ loading, onAnalyze }: EmptyStateProps) {
    return (
        <div>
            <div className="mb-8">
                <h2 className="text-2xl font-semibold text-slate-900">
                    Start a new redline review
                </h2>

                <p className="mt-2 text-sm text-slate-500">
                    Provide the three documents required to compare and review
                    the dealer agreement.
                </p>
            </div>

            <DocumentUpload loading={loading} onAnalyze={onAnalyze} />
        </div>
    );
}

export default EmptyState;
