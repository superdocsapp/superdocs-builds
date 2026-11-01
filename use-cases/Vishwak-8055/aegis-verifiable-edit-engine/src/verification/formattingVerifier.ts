import type { VerificationContext } from '../types/context.js';
import type { CheckerOutcome, Finding } from '../types/verification.js';
import { findBlock, type BlockAlignment } from './normalize.js';
import { blockPlainText } from '../types/document.js';

export function runFormattingVerifier(ctx: VerificationContext): CheckerOutcome {
  const start = performance.now();
  const findings: Finding[] = [];
  let counter = 0;
  const nextId = () => `formatting:${++counter}`;

  for (const entry of ctx.alignment) {
    if (entry.kind !== 'modified') continue;
    findings.push(...compareFormatting(ctx, entry, nextId));
  }

  return { checker: 'formatting', findings, durationMs: performance.now() - start };
}

function compareFormatting(ctx: VerificationContext, entry: Extract<BlockAlignment, { kind: 'modified' }>, nextId: () => string): Finding[] {
  const findings: Finding[] = [];
  const before = findBlock(ctx.before, entry.beforeId);
  const after = findBlock(ctx.after, entry.afterId);
  if (!before || !after) return findings;

  const beforeText = blockPlainText(before);
  const afterText = blockPlainText(after);
  const location = { beforeBlockId: entry.beforeId, afterBlockId: entry.afterId };

  if (stripEmphasis(beforeText) === stripEmphasis(afterText) && beforeText !== afterText) {
    findings.push({
      id: nextId(),
      checker: 'formatting',
      kind: 'FORMATTING_ONLY_CHANGE',
      confidence: 1,
      message: 'The underlying text is identical; only emphasis markup (bold/italic/underline) changed.',
      before: beforeText,
      after: afterText,
      location,
    });
  }

  if (hasUnbalancedEmphasis(afterText) && !hasUnbalancedEmphasis(beforeText)) {
    findings.push({
      id: nextId(),
      checker: 'formatting',
      kind: 'FORMATTING_MARKER_UNBALANCED',
      confidence: 0.8,
      message: 'The result has an unbalanced emphasis marker (e.g. an unmatched "**"), which usually indicates corrupted formatting rather than an intentional style change.',
      after: afterText,
      location,
    });
  }

  return findings;
}

function stripEmphasis(text: string): string {
  return text
    .replace(/\*\*(.+?)\*\*/g, '$1')
    .replace(/\*(.+?)\*/g, '$1')
    .replace(/_(.+?)_/g, '$1');
}

function hasUnbalancedEmphasis(text: string): boolean {
  const doubleStars = (text.match(/\*\*/g) ?? []).length;
  const singleMarkersOnly = text.replace(/\*\*/g, '');
  const singleStars = (singleMarkersOnly.match(/\*/g) ?? []).length;
  const underscores = (text.match(/_/g) ?? []).length;
  return doubleStars % 2 !== 0 || singleStars % 2 !== 0 || underscores % 2 !== 0;
}
