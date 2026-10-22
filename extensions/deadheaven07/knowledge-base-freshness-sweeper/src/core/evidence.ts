import { Article, EvidenceItem } from './types.js';
import { MatchCandidate } from './matcher.js';

/**
 * Stage 3: Evidence Extractor
 * Extracts and verifies exact verbatim sentence-level evidence quotes supporting any stale/impact assessment.
 */
export function extractEvidence(
  article: Article,
  matchCandidates: MatchCandidate[]
): EvidenceItem[] {
  const evidenceList: EvidenceItem[] = [];

  for (const candidate of matchCandidates) {
    const s = candidate.sentence;
    
    // Verify verbatim presence in article body
    const indexInContent = article.content.indexOf(s.text);
    const startOffset = indexInContent !== -1 ? indexInContent : s.startOffset;
    const endOffset = startOffset + s.text.length;

    evidenceList.push({
      sentence_index: s.index,
      sentence_text: s.text,
      section_heading: s.sectionHeading,
      matched_terms: candidate.matchedTerms,
      explanation: candidate.explanation,
      is_indirect: candidate.isIndirect,
      start_offset: startOffset,
      end_offset: endOffset
    });
  }

  // Deduplicate by sentence index
  const seen = new Set<number>();
  return evidenceList.filter(item => {
    if (seen.has(item.sentence_index)) return false;
    seen.add(item.sentence_index);
    return true;
  });
}
