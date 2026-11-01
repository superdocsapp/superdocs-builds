import { parse as parseHtml } from "node-html-parser";
import type { ChangeKind, DocumentChange, DocumentDiffResult, IntegrityCheckResult } from "../types.js";

/**
 * Document integrity checking for SuperDocs-shaped HTML.
 *
 * SuperDocs documents carry `data-chunk-id` on every paragraph, heading,
 * table row/cell (confirmed against the live API docs at
 * docs.superdocs.app/concepts/documents). That gives us a stable join key
 * between a "before" and "after" document, so this diff is chunk-level, not
 * a fragile text diff over the whole HTML string.
 *
 * This module answers exactly one question, precisely: when an operation
 * claims to change only X, did anything else change? "Change only the
 * title" must produce changedFieldCount === 1 and nothing else -- see
 * checkIntegrity below and tests/e2e for the concrete Alice regression case.
 */

interface DocumentChunk {
  chunkId: string;
  tagName: string;
  attributes: Record<string, string>;
  textContent: string;
  order: number;
}

const TRACKED_ATTRS = ["style", "class"] as const;

function extractChunks(html: string): DocumentChunk[] {
  const root = parseHtml(html);
  const elements = root.querySelectorAll("[data-chunk-id]");
  return elements.map((el: any, order: number) => {
    const attributes: Record<string, string> = {};
    for (const attr of TRACKED_ATTRS) {
      const value = el.getAttribute(attr);
      if (value !== undefined) attributes[attr] = value;
    }
    return {
      chunkId: el.getAttribute("data-chunk-id") ?? `__unkeyed_${order}`,
      tagName: el.tagName.toLowerCase(),
      attributes,
      textContent: el.textContent.replace(/\s+/g, " ").trim(),
      order,
    };
  });
}

function attrsEqual(a: Record<string, string>, b: Record<string, string>): boolean {
  const keys = new Set([...Object.keys(a), ...Object.keys(b)]);
  for (const k of keys) {
    if (a[k] !== b[k]) return false;
  }
  return true;
}

/** Longest increasing subsequence, by value -- used to find the minimal set of chunks that changed position. Standard O(n log n) patience-sorting form. */
function longestIncreasingSubsequenceIndices(seq: number[]): Set<number> {
  const predecessors = new Array<number>(seq.length).fill(-1);
  const pileTops: number[] = []; // indices into seq, one per pile, increasing by seq value
  for (let i = 0; i < seq.length; i++) {
    const value = seq[i]!;
    let lo = 0;
    let hi = pileTops.length;
    while (lo < hi) {
      const mid = (lo + hi) >> 1;
      if (seq[pileTops[mid]!]! < value) lo = mid + 1;
      else hi = mid;
    }
    if (lo > 0) predecessors[i] = pileTops[lo - 1]!;
    if (lo === pileTops.length) pileTops.push(i);
    else pileTops[lo] = i;
  }
  const result = new Set<number>();
  let k = pileTops.length ? pileTops[pileTops.length - 1]! : -1;
  while (k !== -1) {
    result.add(k);
    k = predecessors[k]!;
  }
  return result;
}

export function diffDocumentBodies(beforeHtml: string, afterHtml: string): DocumentDiffResult {
  const before = extractChunks(beforeHtml);
  const after = extractChunks(afterHtml);
  const beforeById = new Map(before.map((c) => [c.chunkId, c]));
  const afterById = new Map(after.map((c) => [c.chunkId, c]));

  const changes: DocumentChange[] = [];

  for (const b of before) {
    const a = afterById.get(b.chunkId);
    if (!a) {
      changes.push({ kind: "structure", location: b.chunkId, before: `<${b.tagName}> "${b.textContent.slice(0, 60)}"`, after: "(deleted)" });
      continue;
    }
    if (a.tagName !== b.tagName) {
      changes.push({ kind: "structure", location: b.chunkId, before: `<${b.tagName}>`, after: `<${a.tagName}>` });
    }
    if (a.textContent !== b.textContent) {
      changes.push({ kind: "text", location: b.chunkId, before: b.textContent, after: a.textContent });
    }
    if (!attrsEqual(a.attributes, b.attributes)) {
      changes.push({
        kind: "formatting",
        location: b.chunkId,
        before: JSON.stringify(b.attributes),
        after: JSON.stringify(a.attributes),
      });
    }
  }

  for (const a of after) {
    if (!beforeById.has(a.chunkId)) {
      changes.push({ kind: "structure", location: a.chunkId, before: "(absent)", after: `<${a.tagName}> "${a.textContent.slice(0, 60)}"` });
    }
  }

  // Ordering: minimal set of commonly-present chunks that changed relative position (LIS technique).
  const commonIds = before.map((c) => c.chunkId).filter((id) => afterById.has(id));
  const afterOrderOf = new Map(after.map((c, i) => [c.chunkId, i]));
  const sequence = commonIds.map((id) => afterOrderOf.get(id)!);
  const keepIndices = longestIncreasingSubsequenceIndices(sequence);
  commonIds.forEach((id, i) => {
    if (!keepIndices.has(i)) {
      const beforeIdx = before.findIndex((c) => c.chunkId === id);
      changes.push({ kind: "ordering", location: id, before: `position ${beforeIdx}`, after: `position ${afterOrderOf.get(id)}` });
    }
  });

  return { changes, changedFieldCount: changes.length };
}

export function diffMetadata(before: Record<string, string | null>, after: Record<string, string | null>): DocumentChange[] {
  const keys = new Set([...Object.keys(before), ...Object.keys(after)]);
  const changes: DocumentChange[] = [];
  for (const key of keys) {
    const b = before[key] ?? "";
    const a = after[key] ?? "";
    if (b !== a) {
      changes.push({ kind: "metadata", location: key, before: b, after: a });
    }
  }
  return changes;
}

export interface ChangeExpectation {
  /** Exact set of (kind, location) pairs this operation is allowed to touch. Anything else found is unexpected. */
  allowed: Array<{ kind: ChangeKind; location: string }>;
}

/**
 * Verifies the invariant: "only intentionally requested changes may change."
 * Give it what actually changed (bodyDiff + optional metadataChanges) and
 * what was supposed to change (expectation); it tells you whether anything
 * unrequested moved.
 */
export function checkIntegrity(
  bodyDiff: DocumentDiffResult,
  metadataChanges: DocumentChange[],
  expectation: ChangeExpectation,
): IntegrityCheckResult {
  const allChanges = [...bodyDiff.changes, ...metadataChanges];
  const isAllowed = (c: DocumentChange) => expectation.allowed.some((a) => a.kind === c.kind && a.location === c.location);
  const unexpectedChanges = allChanges.filter((c) => !isAllowed(c));
  return {
    expectedChangeCount: expectation.allowed.length,
    actualChangeCount: allChanges.length,
    pass: unexpectedChanges.length === 0,
    unexpectedChanges,
    diff: { changes: allChanges, changedFieldCount: allChanges.length },
  };
}
