// @ts-check
/**
 * Builds a DiffSnapshot.
 *
 * Shape is deliberately modeled on the real, engine-agnostic contract found
 * in the actual SuperDoc monorepo at
 * packages/document-api/src/diff/diff.types.ts (DiffSnapshot / DiffCoverage):
 *
 *   interface DiffSnapshot {
 *     version: 'sd-diff-snapshot/v1' | 'sd-diff-snapshot/v2';
 *     engine: DiffEngineId;              // 'superdoc-v2' in the real engine
 *     fingerprint: string;
 *     coverage: DiffCoverage;
 *     payload: Record<string, unknown>;  // OPAQUE in the real engine
 *   }
 *
 * IMPORTANT — where this deliberately diverges:
 *   - `engine` here is 'prism-delta-v1', never 'superdoc-v2'. This is not
 *     SuperDoc's engine, and claiming its id would misrepresent the source
 *     of the payload.
 *   - `payload` here is TRANSPARENT (real paragraph objects), not opaque.
 *     The real engine's payload is intentionally opaque to consumers; the
 *     real diffing happens inside packages/superdoc, which is a built,
 *     browser/Node runtime this standalone package does not import (see
 *     README "Why this isn't wired to the real engine").
 *   - `coverage` only ever reports `body: true` and everything else false —
 *     this module reads body paragraphs only (see read-docx.js scope note).
 */
import { createHash } from 'node:crypto';

/** @typedef {{ sourcePath: string, paragraphs: Array<{text: string, styleId: string|null, runs: Array<{text:string,bold:boolean,italic:boolean,underline:boolean}>}> }} ReadDocxResult */

/**
 * Deterministic, collision-resistant-for-this-scope fingerprint of a
 * paragraph array. Shared by snapshotDocument (diffing) and PRISM VAULT
 * (versioning) so there is exactly one hashing algorithm for "what state is
 * this," not two that could silently disagree.
 * @param {Array<{text: string, styleId: string|null, runs: Array<{text:string,bold:boolean,italic:boolean,underline:boolean}>}>} paragraphs
 * @returns {string}
 */
export function fingerprintParagraphs(paragraphs) {
  const fingerprintInput = JSON.stringify(
    paragraphs.map((p) => ({
      text: p.text,
      styleId: p.styleId,
      runs: p.runs.map((r) => ({ text: r.text, bold: r.bold, italic: r.italic, underline: r.underline })),
    })),
  );
  return createHash('sha256').update(fingerprintInput).digest('hex');
}

/**
 * @param {ReadDocxResult} doc
 * @returns {{version: string, engine: string, fingerprint: string, coverage: object, payload: ReadDocxResult}}
 */
export function snapshotDocument(doc) {
  const fingerprint = fingerprintParagraphs(doc.paragraphs);

  return {
    version: 'prism-delta-snapshot/v1',
    engine: 'prism-delta-v1',
    fingerprint,
    coverage: {
      body: true,
      comments: false,
      styles: false,
      numbering: false,
      headerFooters: false,
    },
    payload: {
      sourcePath: doc.sourcePath,
      paragraphs: doc.paragraphs,
    },
  };
}
