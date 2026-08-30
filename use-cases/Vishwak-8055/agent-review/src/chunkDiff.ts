/**
 * Chunk-level differ over SuperDocs document HTML.
 *
 * SuperDocs stamps a `data-chunk-id` attribute on every addressable element
 * (paragraph, heading, table, row, cell — whatever granularity the platform
 * chose when it parsed the document). On the default auto-apply edit path,
 * SuperDocs's API only returns the new whole-document HTML, not a
 * structured diff (see docs/IMPLEMENTATION_PLAN.md §3.3) — a structured diff
 * only shows up when the caller opts into human-in-the-loop mode. This
 * module reconstructs the same shape of diff that HITL mode gets for free,
 * so both paths feed the exact same downstream `Change` model.
 *
 * Deliberately dependency-free: SuperDocs HTML is well-formed and the only
 * thing this needs to do is find every `data-chunk-id`-bearing element and
 * capture its full outer HTML via tag-depth matching, not build a general
 * HTML parser or DOM.
 */

export interface ChunkDiffEntry {
  chunkId: string;
  operation: "edit" | "create" | "delete";
  beforeHtml: string | null;
  afterHtml: string | null;
  /** Only meaningful for `create`: the nearest preceding chunk id present in both snapshots. */
  insertAfterChunkId: string | null;
}

const OPEN_TAG_WITH_CHUNK_ID =
  /<([a-zA-Z][a-zA-Z0-9-]*)\b[^>]*\bdata-chunk-id\s*=\s*"([^"]+)"[^>]*>/g;

// Elements that never have a matching close tag / meaningful chunk body.
const VOID_ELEMENTS = new Set([
  "area", "base", "br", "col", "embed", "hr", "img", "input",
  "link", "meta", "param", "source", "track", "wbr",
]);

/**
 * Parse `html` into an ordered map of chunkId -> that element's full outer HTML.
 * Iteration order matches document order (top to bottom), which the differ
 * relies on to compute a sensible `insertAfterChunkId` for newly created chunks.
 */
export function parseChunks(html: string): Map<string, string> {
  const chunks = new Map<string, string>();
  const duplicateIds = new Set<string>();
  OPEN_TAG_WITH_CHUNK_ID.lastIndex = 0;

  let match: RegExpExecArray | null;
  while ((match = OPEN_TAG_WITH_CHUNK_ID.exec(html)) !== null) {
    const tagName = match[1] as string;
    const chunkId = match[2] as string;
    const openTagEnd = OPEN_TAG_WITH_CHUNK_ID.lastIndex;

    if (chunks.has(chunkId)) duplicateIds.add(chunkId);

    if (VOID_ELEMENTS.has(tagName.toLowerCase()) || match[0].endsWith("/>")) {
      chunks.set(chunkId, match[0]);
      continue;
    }

    const outer = extractBalanced(html, tagName, openTagEnd);
    if (outer === null) {
      // Malformed / unclosed tag. Don't silently guess at content — skip it
      // rather than recording a truncated or wrong chunk body.
      continue;
    }
    chunks.set(chunkId, match[0] + outer.inner + outer.closeTag);
    // Resume scanning AFTER this element's own closing tag. A nested
    // data-chunk-id (e.g. a table row/cell inside a chunked table) is
    // therefore treated as part of *this* chunk's content, not captured a
    // second time as its own overlapping top-level entry. Top-level,
    // non-overlapping chunks are the only ones safe to flatten back into a
    // full document with serializeChunks — capturing nested ids as
    // separate entries here would duplicate their content on write-back
    // (it exists both inside the parent's blob and as its own entry).
    OPEN_TAG_WITH_CHUNK_ID.lastIndex = openTagEnd + outer.inner.length + outer.closeTag.length;
  }

  if (duplicateIds.size > 0) {
    // A document that reuses a chunk id can't be safely diffed (which
    // occurrence changed?) or serialized (later entries silently
    // overwrite earlier ones in the map) — surface this rather than
    // quietly returning a lossy result. Callers that need to distinguish
    // this from "no chunks at all" should check `getLastParseDuplicateIds()`.
    lastParseDuplicateIds = duplicateIds;
  } else {
    lastParseDuplicateIds = null;
  }

  return chunks;
}

/**
 * Set by the most recent `parseChunks` call when the document reused a
 * `data-chunk-id`. Checked by `diffDocumentHtml`/`canSafelyRoundTrip` to
 * refuse rather than silently produce a misleading result — see their
 * docstrings. Module-level rather than a return-value change to
 * `parseChunks` so its primary return type (a plain chunk map) stays
 * simple for the common, non-duplicate case.
 */
let lastParseDuplicateIds: Set<string> | null = null;
export function getLastParseDuplicateIds(): Set<string> | null {
  return lastParseDuplicateIds;
}

function extractBalanced(
  html: string,
  tagName: string,
  fromIndex: number
): { inner: string; closeTag: string } | null {
  const openRe = new RegExp(`<${tagName}\\b[^>]*>`, "gi");
  const closeRe = new RegExp(`</${tagName}\\s*>`, "gi");
  openRe.lastIndex = fromIndex;
  closeRe.lastIndex = fromIndex;

  let depth = 1;
  let cursor = fromIndex;
  while (depth > 0) {
    openRe.lastIndex = cursor;
    closeRe.lastIndex = cursor;
    const nextOpen = openRe.exec(html);
    const nextClose = closeRe.exec(html);
    if (!nextClose) return null; // unclosed — malformed input

    if (nextOpen && nextOpen.index < nextClose.index && !nextOpen[0].endsWith("/>")) {
      depth += 1;
      cursor = nextOpen.index + nextOpen[0].length;
    } else {
      depth -= 1;
      cursor = nextClose.index + nextClose[0].length;
      if (depth === 0) {
        return {
          inner: html.slice(fromIndex, nextClose.index),
          closeTag: nextClose[0],
        };
      }
    }
  }
  return null;
}

/**
 * Diff two chunk snapshots into a normalized list of edit/create/delete
 * operations. Unchanged chunks (identical outer HTML) are omitted.
 */
export function diffChunkMaps(
  before: Map<string, string>,
  after: Map<string, string>
): ChunkDiffEntry[] {
  const entries: ChunkDiffEntry[] = [];
  const afterIds = [...after.keys()];
  const beforeIds = [...before.keys()];

  for (let i = 0; i < beforeIds.length; i++) {
    const chunkId = beforeIds[i] as string;
    if (after.has(chunkId)) continue;
    const beforeHtml = before.get(chunkId) as string;

    // Anchor for re-insertion if this delete is later reverted: the nearest
    // earlier chunk (in the pre-delete document) that's still present.
    let insertAfterChunkId: string | null = null;
    for (let j = i - 1; j >= 0; j--) {
      const candidate = beforeIds[j] as string;
      if (after.has(candidate)) {
        insertAfterChunkId = candidate;
        break;
      }
    }

    entries.push({
      chunkId,
      operation: "delete",
      beforeHtml,
      afterHtml: null,
      insertAfterChunkId,
    });
  }

  for (let i = 0; i < afterIds.length; i++) {
    const chunkId = afterIds[i] as string;
    const afterHtml = after.get(chunkId) as string;
    if (!before.has(chunkId)) {
      // Newly created chunk: anchor it to the nearest earlier chunk id that
      // existed in both snapshots, so the review UI can place it correctly
      // without needing to diff the raw document structure itself.
      let insertAfterChunkId: string | null = null;
      for (let j = i - 1; j >= 0; j--) {
        const candidate = afterIds[j] as string;
        if (before.has(candidate)) {
          insertAfterChunkId = candidate;
          break;
        }
      }
      entries.push({
        chunkId,
        operation: "create",
        beforeHtml: null,
        afterHtml,
        insertAfterChunkId,
      });
    } else if (before.get(chunkId) !== afterHtml) {
      entries.push({
        chunkId,
        operation: "edit",
        beforeHtml: before.get(chunkId) as string,
        afterHtml,
        insertAfterChunkId: null,
      });
    }
  }

  return entries;
}

/**
 * Thrown by `diffDocumentHtml` instead of returning a diff when either
 * snapshot reuses a `data-chunk-id` — with a duplicate id, `parseChunks`
 * can only keep one occurrence (a `Map` key can't hold two values), so a
 * diff computed from it would be silently incomplete or simply wrong about
 * which occurrence changed. Per the principle that this engine never
 * silently produces a misleading diff, callers must catch this and mark
 * the turn unsafe/ambiguous for a human to resolve rather than review a
 * diff that might not reflect reality.
 */
export class DuplicateChunkIdError extends Error {
  constructor(public readonly duplicateIds: string[]) {
    super(`Cannot safely diff: duplicate data-chunk-id value(s) found: ${duplicateIds.join(", ")}`);
    this.name = "DuplicateChunkIdError";
  }
}

/** Convenience wrapper: diff two raw HTML documents directly. */
export function diffDocumentHtml(beforeHtml: string, afterHtml: string): ChunkDiffEntry[] {
  const before = parseChunks(beforeHtml);
  const beforeDuplicates = getLastParseDuplicateIds();
  const after = parseChunks(afterHtml);
  const afterDuplicates = getLastParseDuplicateIds();

  const allDuplicates = new Set([...(beforeDuplicates ?? []), ...(afterDuplicates ?? [])]);
  if (allDuplicates.size > 0) {
    throw new DuplicateChunkIdError([...allDuplicates]);
  }

  return diffChunkMaps(before, after);
}

/** Inverse of parseChunks: flattens a chunk map back into a single HTML document, preserving map iteration (= document) order. */
export function serializeChunks(chunks: ReadonlyMap<string, string>): string {
  return [...chunks.values()].join("");
}

/**
 * True if parsing then re-serializing `html` reproduces it byte-for-byte.
 *
 * This document's chunk model may not be complete — a wrapper element
 * around all the chunks, whitespace or text between them, attributes we
 * don't preserve — and this sandbox could not verify SuperDocs's real
 * document HTML shape against a live account (docs/SECURITY.md). Rather
 * than assume the model is complete, this checks it empirically against
 * the actual content in front of us: any live write-back MUST call this
 * first and refuse to proceed on `false`, because writing a reconstruction
 * that doesn't round-trip risks silently dropping or corrupting content
 * outside this model — exactly the failure mode "safe revert" exists to
 * prevent. See `liveSideEffects.ts`.
 */
export function canSafelyRoundTrip(html: string): boolean {
  return serializeChunks(parseChunks(html)) === html;
}
