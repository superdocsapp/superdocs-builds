// @ts-check
export { classifyModifiedParagraph, classifyCommonPair, classifyStructuralBlock } from './classify/classify-change.js';
export { buildDeltaReport } from './report/build-report.js';

import { readDocx, snapshotDocument } from '@prism/core';
import { buildDeltaReport } from './report/build-report.js';

/**
 * End-to-end: two .docx paths in, a DiffPayload-shaped report out.
 * @param {string} basePath
 * @param {string} targetPath
 */
export async function compareFiles(basePath, targetPath) {
  const [baseDoc, targetDoc] = await Promise.all([readDocx(basePath), readDocx(targetPath)]);
  const baseSnapshot = snapshotDocument(baseDoc);
  const targetSnapshot = snapshotDocument(targetDoc);
  const report = buildDeltaReport(baseSnapshot, targetSnapshot);
  // Carried through for PRISM GATE, which needs to re-derive the same
  // aligned ops deterministically to apply an approved subset — see
  // packages/gate/src/apply.js.
  return { ...report, baseDoc, targetDoc };
}
