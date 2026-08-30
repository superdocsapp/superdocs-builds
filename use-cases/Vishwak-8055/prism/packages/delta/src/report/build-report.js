// @ts-check
import { alignParagraphs } from '@prism/core';
import { classifyModifiedParagraph, classifyCommonPair, classifyStructuralBlock } from '../classify/classify-change.js';

/**
 * @typedef {{version: string, engine: string, fingerprint: string, coverage: object, payload: {sourcePath: string, paragraphs: Array<{text: string, styleId: string|null, runs: object[]}>}}} Snapshot
 */

/**
 * @param {Snapshot} baseSnapshot
 * @param {Snapshot} targetSnapshot
 */
export function buildDeltaReport(baseSnapshot, targetSnapshot) {
  const ops = alignParagraphs(baseSnapshot.payload, targetSnapshot.payload);

  const changes = [];
  ops.forEach((op, opIndex) => {
    if (op.type === 'modified') {
      changes.push({ ...classifyModifiedParagraph(op.base, op.target), opIndex });
    } else if (op.type === 'common') {
      const formatChange = classifyCommonPair(op.base, op.target);
      if (formatChange) changes.push({ ...formatChange, opIndex });
    } else if (op.type === 'added') {
      changes.push({ ...classifyStructuralBlock('added', op.items), opIndex });
    } else if (op.type === 'removed') {
      changes.push({ ...classifyStructuralBlock('removed', op.items), opIndex });
    }
  });

  const materialChanges = changes.filter((c) => c.findings.some((f) => f.materiality === 'material'));
  const reviewRequiredChanges = changes.filter((c) => c.findings.some((f) => f.materiality === 'review-required'));
  const cosmeticOnlyChanges = changes.filter((c) => c.findings.every((f) => f.materiality === 'cosmetic' || f.materiality === 'minor'));

  const hasChanges = changes.length > 0;

  return {
    version: 'prism-delta-payload/v1',
    engine: 'prism-delta-v1',
    baseFingerprint: baseSnapshot.fingerprint,
    targetFingerprint: targetSnapshot.fingerprint,
    coverage: baseSnapshot.coverage,
    // Shape mirrors the real DiffSummary from SuperDoc's document-api, plus
    // the categorical breakdown PRISM DELTA adds on top.
    summary: {
      hasChanges,
      changedComponents: hasChanges ? ['body'] : [],
      body: { hasChanges },
      comments: { hasChanges: false },
      styles: { hasChanges: false },
      numbering: { hasChanges: false },
      headerFooters: { hasChanges: false },
      parts: { hasChanges: false },
      totalChanges: changes.length,
      materialChangeCount: materialChanges.length,
      reviewRequiredCount: reviewRequiredChanges.length,
      cosmeticOnlyCount: cosmeticOnlyChanges.length,
    },
    changes,
    // Every aligned op, including untouched 'common' pairs that never became
    // a `changes[]` entry. PRISM GATE needs the full sequence to reconstruct
    // a complete document from an approved subset, not just the notable
    // parts. Internal contract with @prism/gate — not meant as a stable
    // public shape beyond this workspace.
    ops,
  };
}
