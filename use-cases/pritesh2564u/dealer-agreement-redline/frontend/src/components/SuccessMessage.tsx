import { CheckCircle2, X } from "lucide-react";

interface SuccessMessageProps {
    message: string;
    onDismiss?: () => void;
}

function SuccessMessage({ message, onDismiss }: SuccessMessageProps) {
    return (
        <div className="mb-6 flex items-center justify-between rounded-lg border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-700">
            <div className="flex items-center gap-3">
                <CheckCircle2 size={18} className="shrink-0" />

                <p>{message}</p>
            </div>

            {onDismiss && (
                <button
                    type="button"
                    onClick={onDismiss}
                    className="ml-4 rounded-md p-1 text-emerald-600 transition hover:bg-emerald-100 hover:text-emerald-800"
                    aria-label="Dismiss message"
                >
                    <X size={16} />
                </button>
            )}
        </div>
    );
}

export default SuccessMessage;
