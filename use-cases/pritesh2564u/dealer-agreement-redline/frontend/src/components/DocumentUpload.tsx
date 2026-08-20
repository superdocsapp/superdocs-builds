import { useState } from "react";

interface DocumentUploadProps {
    onAnalyze: (dealerFile: File, masterFile: File, playbookFile: File) => void;

    loading: boolean;
}

interface FilePickerProps {
    label: string;
    description: string;
    file: File | null;
    onChange: (file: File | null) => void;
    disabled: boolean;
}

function FilePicker({
    label,
    description,
    file,
    onChange,
    disabled,
}: FilePickerProps) {
    function handleChange(event: React.ChangeEvent<HTMLInputElement>) {
        const selectedFile = event.target.files?.[0] ?? null;

        onChange(selectedFile);
    }

    return (
        <div className="rounded-xl border border-slate-200 bg-white p-5">
            <div>
                <h3 className="font-semibold text-slate-900">{label}</h3>

                <p className="mt-1 text-sm text-slate-500">{description}</p>
            </div>

            <label
                className={`mt-4 flex cursor-pointer items-center justify-between rounded-lg border border-dashed border-slate-300 px-4 py-4 transition hover:border-slate-500 hover:bg-slate-50 ${
                    disabled ? "cursor-not-allowed opacity-50" : ""
                }`}
            >
                <div className="min-w-0">
                    {file ? (
                        <>
                            <p className="truncate text-sm font-medium text-slate-900">
                                {file.name}
                            </p>

                            <p className="mt-1 text-xs text-slate-500">
                                {(file.size / 1024).toFixed(1)} KB
                            </p>
                        </>
                    ) : (
                        <p className="text-sm text-slate-500">
                            Choose a DOCX file
                        </p>
                    )}
                </div>

                <span className="ml-4 shrink-0 rounded-lg bg-slate-100 px-3 py-2 text-xs font-medium text-slate-700">
                    Browse
                </span>

                <input
                    type="file"
                    accept=".docx,application/vnd.openxmlformats-officedocument.wordprocessingml.document"
                    className="hidden"
                    onChange={handleChange}
                    disabled={disabled}
                />
            </label>
        </div>
    );
}

function DocumentUpload({ onAnalyze, loading }: DocumentUploadProps) {
    const [dealerFile, setDealerFile] = useState<File | null>(null);

    const [masterFile, setMasterFile] = useState<File | null>(null);

    const [playbookFile, setPlaybookFile] = useState<File | null>(null);

    const canAnalyze =
        dealerFile !== null &&
        masterFile !== null &&
        playbookFile !== null &&
        !loading;

    function handleAnalyze() {
        if (!dealerFile || !masterFile || !playbookFile) {
            return;
        }

        onAnalyze(dealerFile, masterFile, playbookFile);
    }

    return (
        <section className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm sm:p-8">
            <div className="mb-6">
                <p className="text-sm font-medium text-slate-500">
                    Document Setup
                </p>

                <h2 className="mt-1 text-xl font-semibold text-slate-900">
                    Upload agreement documents
                </h2>

                <p className="mt-2 max-w-2xl text-sm leading-6 text-slate-500">
                    Upload the dealer agreement, approved master agreement, and
                    negotiation playbook to begin the redline review.
                </p>
            </div>

            <div className="grid gap-4 lg:grid-cols-3">
                <FilePicker
                    label="Dealer Agreement"
                    description="The returned agreement to review."
                    file={dealerFile}
                    onChange={setDealerFile}
                    disabled={loading}
                />

                <FilePicker
                    label="Master Agreement"
                    description="The approved agreement to compare against."
                    file={masterFile}
                    onChange={setMasterFile}
                    disabled={loading}
                />

                <FilePicker
                    label="Negotiation Playbook"
                    description="Rules for classifying deviations."
                    file={playbookFile}
                    onChange={setPlaybookFile}
                    disabled={loading}
                />
            </div>

            <div className="mt-6 flex justify-end">
                <button
                    type="button"
                    onClick={handleAnalyze}
                    disabled={!canAnalyze}
                    className="rounded-lg bg-slate-900 px-6 py-3 text-sm font-medium text-white transition hover:bg-slate-700 disabled:cursor-not-allowed disabled:opacity-40"
                >
                    {loading ? "Analyzing..." : "Analyze Agreement"}
                </button>
            </div>
        </section>
    );
}

export default DocumentUpload;
