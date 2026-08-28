import type { ReactNode } from "react";

export interface MasterDetailProps {
  listPanel: ReactNode;
  detailPanel: ReactNode;
  hasSelection: boolean;
  onBack?: () => void;
}

/**
 * Responsive master-detail layout.
 * - Desktop (md: ≥768px): side-by-side split — list 40%, detail 60%.
 * - Mobile (<768px): stacked single-column with navigation state.
 *   Shows list when hasSelection is false, detail with back button when true.
 */
export function MasterDetail({
  listPanel,
  detailPanel,
  hasSelection,
  onBack,
}: MasterDetailProps) {
  return (
    <div className="flex h-full w-full flex-col md:flex-row">
      {/* List panel — always visible on desktop, hidden on mobile when detail is shown */}
      <div
        className={`h-full md:block md:w-2/5 ${
          hasSelection ? "hidden" : "block"
        }`}
      >
        {listPanel}
      </div>

      {/* Gradient divider line */}
      <div className="hidden md:block w-px bg-gradient-to-b from-transparent via-white/[0.08] to-transparent" aria-hidden="true" />

      {/* Detail panel — always visible on desktop, hidden on mobile when list is shown */}
      <div
        className={`h-full md:block md:flex-1 ${
          hasSelection ? "block" : "hidden"
        }`}
      >
        {/* Back button — only shown on mobile when detail is visible */}
        {hasSelection && (
          <div className="border-b border-white/[0.06] p-2 md:hidden">
            <button
              type="button"
              onClick={onBack}
              aria-label="Back to queue list"
              className="flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-sm text-white/50 transition-colors hover:bg-white/[0.05] hover:text-white/70 focus:outline-none focus:ring-2 focus:ring-indigo-500/50"
            >
              <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" strokeWidth={1.5} stroke="currentColor" aria-hidden="true">
                <path strokeLinecap="round" strokeLinejoin="round" d="M15.75 19.5L8.25 12l7.5-7.5" />
              </svg>
              <span>Back</span>
            </button>
          </div>
        )}
        {detailPanel}
      </div>
    </div>
  );
}
