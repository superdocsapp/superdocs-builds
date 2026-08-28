import { getCitationLabel, isUnverifiable } from "@/utils/citationHelpers";
import type { SourceCitation } from "@/types/review";

interface CitationChipProps {
  citation: SourceCitation;
}

/**
 * Renders a small inline chip indicating whether a citation is grounded
 * or unverifiable. Applies a warning pulse animation for unverifiable citations.
 */
export function CitationChip({ citation }: CitationChipProps) {
  const unverifiable = isUnverifiable(citation);
  const label = getCitationLabel(citation);

  const baseClasses =
    "inline-flex items-center rounded-md border px-2 py-0.5 text-xs font-medium transition-all";

  const colorClasses = unverifiable
    ? "bg-amber-500/10 text-amber-300 border-amber-500/20 warning-pulse"
    : "border-white/[0.08] text-white/60 bg-white/[0.03]";

  return (
    <span
      className={`${baseClasses} ${colorClasses}`}
      title={citation.snippet ? `"${citation.snippet}"` : undefined}
      aria-label={
        unverifiable
          ? "Citation unverifiable"
          : `Citation grounded: ${label}`
      }
    >
      {unverifiable && (
        <svg className="h-3 w-3 mr-1 text-amber-400" viewBox="0 0 16 16" fill="currentColor" aria-hidden="true">
          <path d="M8 1.5a.75.75 0 01.65.38l5.75 10a.75.75 0 01-.65 1.12H2.25a.75.75 0 01-.65-1.12l5.75-10A.75.75 0 018 1.5zM8 5.5a.75.75 0 00-.75.75v2.5a.75.75 0 001.5 0v-2.5A.75.75 0 008 5.5zM8 11a.75.75 0 100 1.5.75.75 0 000-1.5z" />
        </svg>
      )}
      {label}
    </span>
  );
}
