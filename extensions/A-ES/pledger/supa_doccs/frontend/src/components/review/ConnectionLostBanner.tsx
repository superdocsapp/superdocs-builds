import React from "react";

export interface ConnectionLostBannerProps {
  connectionLost: boolean;
  onDismiss?: () => void;
}

/**
 * Displays a dismissible warning banner when the polling service
 * loses connectivity to the backend. Uses ARIA role="alert" for
 * immediate screen reader announcement.
 *
 * Validates: Requirements 11.3, 9.3
 */
export const ConnectionLostBanner: React.FC<ConnectionLostBannerProps> = ({
  connectionLost,
  onDismiss,
}) => {
  if (!connectionLost) {
    return null;
  }

  return (
    <div
      role="alert"
      aria-live="assertive"
      className="fixed top-16 left-1/2 z-50 -translate-x-1/2 flex items-center gap-3 rounded-xl border border-amber-500/20 bg-surface-elevated/90 px-5 py-3 shadow-2xl shadow-amber-500/10 backdrop-blur-xl"
    >
      <div className="flex items-center gap-2.5">
        <span className="flex h-6 w-6 items-center justify-center rounded-full bg-amber-500/15 warning-pulse">
          <svg
            aria-hidden="true"
            className="h-3.5 w-3.5 text-amber-400"
            fill="none"
            viewBox="0 0 24 24"
            strokeWidth={2}
            stroke="currentColor"
          >
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              d="M12 9v3.75m-9.303 3.376c-.866 1.5.217 3.374 1.948 3.374h14.71c1.73 0 2.813-1.874 1.948-3.374L13.949 3.378c-.866-1.5-3.032-1.5-3.898 0L2.697 16.126ZM12 15.75h.007v.008H12v-.008Z"
            />
          </svg>
        </span>
        <span className="text-sm font-medium text-amber-200/90">
          Connection lost. Data may be stale. Retrying...
        </span>
      </div>
      {onDismiss && (
        <button
          type="button"
          onClick={onDismiss}
          aria-label="Dismiss connection warning"
          className="ml-2 rounded-lg p-1.5 text-white/40 transition-colors hover:bg-white/[0.06] hover:text-white/70 focus:outline-none focus:ring-2 focus:ring-amber-400/50"
        >
          <svg
            aria-hidden="true"
            className="h-3.5 w-3.5"
            fill="none"
            viewBox="0 0 24 24"
            strokeWidth={2}
            stroke="currentColor"
          >
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              d="M6 18L18 6M6 6l12 12"
            />
          </svg>
        </button>
      )}
    </div>
  );
};

export default ConnectionLostBanner;
