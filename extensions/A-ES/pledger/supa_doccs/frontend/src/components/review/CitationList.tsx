import type { SourceCitation } from "@/types/review";
import { CitationChip } from "./CitationChip";

interface CitationListProps {
  citations: SourceCitation[];
}

/**
 * Renders an array of CitationChip components with a count header.
 */
export function CitationList({ citations }: CitationListProps) {
  return (
    <section aria-label="Source citations">
      <h3 className="mb-2 text-xs font-medium uppercase tracking-wider text-white/40">
        Source Citations ({citations.length})
      </h3>
      {citations.length === 0 ? (
        <p className="text-sm text-white/30">No citations available.</p>
      ) : (
        <div className="flex flex-wrap gap-2">
          {citations.map((citation) => (
            <CitationChip key={citation.claim_id} citation={citation} />
          ))}
        </div>
      )}
    </section>
  );
}
