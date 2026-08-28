import type { SourceCitation } from "@/types/review";

/**
 * Returns true if the citation is unverifiable — either by explicit status
 * or because source_location is null.
 */
export function isUnverifiable(citation: SourceCitation): boolean {
  return (
    citation.citation_status === "unverifiable" ||
    citation.source_location === null
  );
}

/**
 * The single item-level definition of "unverifiable evidence".
 *
 * An item counts as unverifiable when it has NO citations at all
 * (empty array) or when EVERY citation is unverifiable (status flag set
 * or source_location null). This is the only definition; call sites
 * (QueueItemCard marker, unverifiable-only filter) must use this function
 * and must not reimplement it.
 */
export function itemIsUnverifiable(citations: SourceCitation[]): boolean {
  return citations.length === 0 || citations.every(isUnverifiable);
}

/**
 * Returns the display label for a citation chip.
 * - Unverifiable citations → "[citation unverifiable]"
 * - Verifiable citations → clause_ref if available, otherwise "p.{page_number}"
 */
export function getCitationLabel(citation: SourceCitation): string {
  if (isUnverifiable(citation)) {
    return "[citation unverifiable]";
  }

  const loc = citation.source_location!;

  if (loc.clause_ref) {
    return loc.clause_ref;
  }

  return `p.${loc.page_number}`;
}
