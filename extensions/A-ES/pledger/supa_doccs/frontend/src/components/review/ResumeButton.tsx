interface ResumeButtonProps {
  /** Whether the button should be visible (typically when run is paused or failed) */
  canResume: boolean;
  /** Whether a resume request is currently in-flight */
  isResuming: boolean;
  /** Callback to trigger the resume action */
  onResume: () => void;
}

export function ResumeButton({ canResume, isResuming, onResume }: ResumeButtonProps) {
  if (!canResume) return null;

  return (
    <button
      type="button"
      onClick={onResume}
      disabled={isResuming}
      aria-label="Resume pipeline run"
      aria-busy={isResuming}
      className="inline-flex items-center gap-1.5 rounded-lg bg-emerald-500 px-3 py-1.5 text-sm font-medium text-white shadow-lg shadow-emerald-500/25 transition-all hover:bg-emerald-400 hover:shadow-emerald-500/30 disabled:opacity-50 disabled:cursor-not-allowed focus:outline-none focus:ring-2 focus:ring-emerald-400 focus:ring-offset-2 focus:ring-offset-surface-base"
    >
      {isResuming ? (
        <>
          <svg
            className="h-4 w-4 animate-spin"
            xmlns="http://www.w3.org/2000/svg"
            fill="none"
            viewBox="0 0 24 24"
            aria-hidden="true"
          >
            <circle
              className="opacity-25"
              cx="12"
              cy="12"
              r="10"
              stroke="currentColor"
              strokeWidth="4"
            />
            <path
              className="opacity-75"
              fill="currentColor"
              d="M4 12a8 8 0 018-8v4a4 4 0 00-4 4H4z"
            />
          </svg>
          Resuming…
        </>
      ) : (
        <>
          <svg
            className="h-4 w-4"
            xmlns="http://www.w3.org/2000/svg"
            viewBox="0 0 20 20"
            fill="currentColor"
            aria-hidden="true"
          >
            <path
              fillRule="evenodd"
              d="M2 10a8 8 0 1116 0 8 8 0 01-16 0zm6.39-2.908a.75.75 0 01.77.038l3.5 2.25a.75.75 0 010 1.24l-3.5 2.25A.75.75 0 018 12.25v-4.5a.75.75 0 01.39-.658z"
              clipRule="evenodd"
            />
          </svg>
          Resume
        </>
      )}
    </button>
  );
}

export default ResumeButton;
