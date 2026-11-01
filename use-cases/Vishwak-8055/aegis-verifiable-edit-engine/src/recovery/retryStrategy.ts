import type { ClassifiedFinding } from '../types/verification.js';
import { severityRank } from '../types/verification.js';

/**
 * A run is only eligible for an automatic retry when EVERY finding at
 * MEDIUM severity or above is individually marked recoverable by policy.
 * A single non-recoverable HIGH/CRITICAL finding (e.g. any protected-value
 * mutation, or the most dangerous semantic mutations — see
 * src/risk/policy.default.json) forces REQUIRES_REVIEW/BLOCKED with no
 * automatic retry, by design: those are exactly the cases a "just try
 * again" loop must not paper over.
 */
export function isRecoverable(findings: readonly ClassifiedFinding[]): boolean {
  return findings.filter((f) => severityRank(f.severity) >= severityRank('MEDIUM')).every((f) => f.recoverable);
}

/**
 * Turns the failed run's findings into an explicit, additive constraint
 * appended to the original instruction. This does not change what the
 * instruction asked for — it only narrows the executor's latitude, which is
 * what makes retrying safe rather than a way to "argue past" verification.
 */
export function buildConstrainedInstruction(originalInstruction: string, findings: readonly ClassifiedFinding[]): string {
  const constraints: string[] = [];

  if (findings.some((f) => f.kind === 'UNINTENDED_SCOPE_CHANGE' || f.kind === 'SCOPE_TARGET_NOT_FOUND')) {
    constraints.push('Do not modify, delete, or add any content outside the specifically requested region.');
  }
  if (findings.some((f) => f.kind === 'STRUCTURAL_BLOCK_DELETED')) {
    constraints.push('Do not delete any paragraphs, headings, list items, or table rows.');
  }
  if (findings.some((f) => f.kind === 'STRUCTURAL_BLOCK_INSERTED')) {
    constraints.push('Do not add any new paragraphs, headings, or sections.');
  }
  if (findings.some((f) => f.kind === 'STRUCTURAL_TABLE_DIMENSION_CHANGED')) {
    constraints.push('Do not add or remove table rows or columns.');
  }

  if (constraints.length === 0) return originalInstruction;
  return `${originalInstruction}\n\n[Automated recovery constraint, added after a failed verification attempt]: ${constraints.join(' ')}`;
}
