export interface ASTPreservationProof {
  originalLengthBytes: number;
  proposedLengthBytes: number;
  headingsPreserved: boolean;
  codeBlocksPreserved: boolean;
  tablesPreserved: boolean;
  linksPreserved: boolean;
  nonTargetBytesPreserved: boolean;
  preservationRatio: number;
  isProofValid: boolean;
}

/**
 * Byte-Level AST Invariance Verifier
 * Rigorously proves that surgical edits mutate only target sentence tokens
 * while maintaining 100% byte invariance for all non-target markdown elements.
 */
export function verifyASTInvariance(
  originalMarkdown: string,
  proposedMarkdown: string,
  targetOriginalSentence: string,
  targetReplacementSentence: string
): ASTPreservationProof {
  const origBytes = Buffer.byteLength(originalMarkdown, 'utf-8');
  const propBytes = Buffer.byteLength(proposedMarkdown, 'utf-8');

  // 1. Heading structure extraction
  const origHeadings = (originalMarkdown.match(/^#{1,6}\s+.+$/gm) || []).join('\n');
  const propHeadings = (proposedMarkdown.match(/^#{1,6}\s+.+$/gm) || []).join('\n');
  const headingsPreserved = origHeadings === propHeadings;

  // 2. Code blocks extraction
  const origCode = (originalMarkdown.match(/```[\s\S]*?```/g) || []).join('\n');
  const propCode = (proposedMarkdown.match(/```[\s\S]*?```/g) || []).join('\n');
  const codeBlocksPreserved = origCode === propCode;

  // 3. Tables extraction
  const origTables = (originalMarkdown.match(/^\|.+$/gm) || []).join('\n');
  const propTables = (proposedMarkdown.match(/^\|.+$/gm) || []).join('\n');
  const tablesPreserved = origTables === propTables;

  // 4. Links extraction
  const origLinks = (originalMarkdown.match(/\[[^\]]+\]\([^)]+\)/g) || []).join('\n');
  const propLinks = (proposedMarkdown.match(/\[[^\]]+\]\([^)]+\)/g) || []).join('\n');
  const linksPreserved = origLinks === propLinks;

  // 5. Non-target byte invariance verification
  // Remove the target sentence from original and replacement from proposed, then compare remaining bytes
  const origStripped = originalMarkdown.replace(targetOriginalSentence, '');
  const propStripped = proposedMarkdown.replace(targetReplacementSentence, '');
  const nonTargetBytesPreserved = origStripped === propStripped;

  // 6. Preservation ratio calculation
  const charDiff = Math.abs(origBytes - propBytes) + Math.abs(targetOriginalSentence.length - targetReplacementSentence.length);
  const preservationRatio = Math.max(0, (origBytes - (charDiff / 2)) / Math.max(1, origBytes));

  const isProofValid =
    headingsPreserved &&
    codeBlocksPreserved &&
    tablesPreserved &&
    linksPreserved &&
    nonTargetBytesPreserved &&
    preservationRatio >= 0.98;

  return {
    originalLengthBytes: origBytes,
    proposedLengthBytes: propBytes,
    headingsPreserved,
    codeBlocksPreserved,
    tablesPreserved,
    linksPreserved,
    nonTargetBytesPreserved,
    preservationRatio: Math.round(preservationRatio * 1000) / 1000,
    isProofValid
  };
}
