import type { VerificationContext } from '../types/context.js';
import type { CheckerOutcome, Finding } from '../types/verification.js';
import { findBlock } from './normalize.js';

export function runStructuralVerifier(ctx: VerificationContext): CheckerOutcome {
  const start = performance.now();
  const findings: Finding[] = [];
  let counter = 0;
  const nextId = () => `structural:${++counter}`;

  for (const entry of ctx.alignment) {
    if (entry.kind === 'inserted') {
      const block = findBlock(ctx.after, entry.afterId);
      findings.push({
        id: nextId(),
        checker: 'structural',
        kind: 'STRUCTURAL_BLOCK_INSERTED',
        confidence: 1,
        message: `A new ${block?.type ?? 'unknown'} block was added that has no counterpart in the original document.`,
        after: block ? summarizeBlock(block) : undefined,
        location: { afterBlockId: entry.afterId },
      });
      continue;
    }

    if (entry.kind === 'deleted') {
      const block = findBlock(ctx.before, entry.beforeId);
      findings.push({
        id: nextId(),
        checker: 'structural',
        kind: 'STRUCTURAL_BLOCK_DELETED',
        confidence: 1,
        message: `A ${block?.type ?? 'unknown'} block present in the original document is missing from the result.`,
        before: block ? summarizeBlock(block) : undefined,
        location: { beforeBlockId: entry.beforeId },
      });
      continue;
    }

    if (entry.kind === 'modified') {
      const before = findBlock(ctx.before, entry.beforeId);
      const after = findBlock(ctx.after, entry.afterId);
      if (!before || !after) continue;
      const location = { beforeBlockId: entry.beforeId, afterBlockId: entry.afterId };

      if (before.type !== after.type) {
        findings.push({
          id: nextId(),
          checker: 'structural',
          kind: 'STRUCTURAL_TYPE_CHANGED',
          confidence: 1,
          message: `Block type changed from ${before.type} to ${after.type}.`,
          before: summarizeBlock(before),
          after: summarizeBlock(after),
          location,
        });
        continue; // type-specific checks below don't apply across a type change
      }

      if (before.type === 'heading' && after.type === 'heading' && before.level !== after.level) {
        findings.push({
          id: nextId(),
          checker: 'structural',
          kind: 'STRUCTURAL_HEADING_LEVEL_CHANGED',
          confidence: 1,
          message: `Heading level changed from H${before.level} to H${after.level}.`,
          before: `H${before.level}: ${before.text}`,
          after: `H${after.level}: ${after.text}`,
          location,
        });
      }

      if (before.type === 'table' && after.type === 'table' && (before.rows !== after.rows || before.cols !== after.cols)) {
        findings.push({
          id: nextId(),
          checker: 'structural',
          kind: 'STRUCTURAL_TABLE_DIMENSION_CHANGED',
          confidence: 1,
          message: `Table dimensions changed from ${before.rows}x${before.cols} to ${after.rows}x${after.cols}.`,
          before: `${before.rows}x${before.cols}`,
          after: `${after.rows}x${after.cols}`,
          location,
        });
      }

      if (before.type === 'paragraph' && after.type === 'paragraph') {
        findings.push(...compareLinks(before.links, after.links, location, nextId));
      }
    }
  }

  return { checker: 'structural', findings, durationMs: performance.now() - start };
}

function compareLinks(
  before: { text: string; href: string }[],
  after: { text: string; href: string }[],
  location: { beforeBlockId?: string; afterBlockId?: string },
  nextId: () => string,
): Finding[] {
  const findings: Finding[] = [];
  const beforeByText = new Map(before.map((l) => [l.text, l.href]));
  const afterByText = new Map(after.map((l) => [l.text, l.href]));

  for (const [text, href] of beforeByText) {
    const afterHref = afterByText.get(text);
    if (afterHref === undefined) {
      findings.push({
        id: nextId(),
        checker: 'structural',
        kind: 'STRUCTURAL_LINK_REMOVED',
        confidence: 0.9,
        message: `Link "${text}" (${href}) is no longer present.`,
        before: `${text} → ${href}`,
        location,
      });
    } else if (afterHref !== href) {
      findings.push({
        id: nextId(),
        checker: 'structural',
        kind: 'STRUCTURAL_LINK_URL_CHANGED',
        confidence: 0.9,
        message: `Link "${text}" now points to a different URL.`,
        before: `${text} → ${href}`,
        after: `${text} → ${afterHref}`,
        location,
      });
    }
  }
  for (const [text, href] of afterByText) {
    if (!beforeByText.has(text)) {
      findings.push({
        id: nextId(),
        checker: 'structural',
        kind: 'STRUCTURAL_LINK_ADDED',
        confidence: 0.9,
        message: `A new link "${text}" (${href}) appeared that was not present before.`,
        after: `${text} → ${href}`,
        location,
      });
    }
  }
  return findings;
}

function summarizeBlock(block: { type: string }): string {
  return `[${block.type}]`;
}
