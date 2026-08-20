interface SuccessMessageProps {
    message: string;
    onDismiss?: () => void;
}

function SuccessMessage({ message, onDismiss }: SuccessMessageProps) {
    return (
        <div className="mb-6 flex items-center justify-between rounded-lg border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-700">
            <p>{message}</p>

            {onDismiss && (
                <button
                    type="button"
                    onClick={onDismiss}
                    className="ml-4 text-emerald-700 hover:text-emerald-900"
                    aria-label="Dismiss message"
                >
                    ×
                </button>
            )}
        </div>
    );
}

export default SuccessMessage;
