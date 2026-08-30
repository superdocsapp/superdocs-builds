import type { Change } from "./types";

/**
 * A concrete, minimal instruction for undoing exactly one Change. Deliberately
 * scoped to a single chunk id — this is what makes revert independence
 * structural rather than best-effort: applying this patch can only ever
 * touch the one chunk it names.
 */
export type RevertPatch =
  | { kind: "restore"; chunkId: string; html: string } // undo an edit
  | { kind: "remove"; chunkId: string } // undo a create
  | { kind: "reinsert"; chunkId: string; html: string; insertAfterChunkId: string | null }; // undo a delete

export type RevertPlan =
  | { safe: true; patch: RevertPatch }
  | { safe: false; reason: string; liveHtml: string | null };

/**
 * Decide whether `change` (must already be `approved`) can be safely
 * reverted against the document's *current* chunk map, and if so, produce
 * the exact patch to apply.
 *
 * "Safe" means: the chunk this change touched is still in exactly the state
 * this change left it in. If anything else has touched that same chunk
 * since — another approved change, a brand new agent turn, a manual edit —
 * this returns `safe: false` instead of guessing. Per
 * docs/IMPLEMENTATION_PLAN.md §6.3, an unsafe revert is never applied
 * automatically; the caller is expected to surface the conflict for a human
 * to resolve (mark the Change `conflicted` via changeModel) rather than
 * silently overwriting whatever is live now.
 *
 * This function does not check `change.status` itself — that's a state
 * -machine concern (changeModel.ts) the caller is expected to have already
 * enforced. Keeping this module purely about *content* safety makes it
 * independently testable against plain fixtures.
 */
export function planRevert(change: Change, liveChunks: ReadonlyMap<string, string>): RevertPlan {
  switch (change.operation) {
    case "edit": {
      if (change.chunkId === null || change.beforeHtml === null) {
        return { safe: false, reason: "malformed edit change: missing chunkId or beforeHtml", liveHtml: null };
      }
      const live = liveChunks.get(change.chunkId);
      if (live === undefined) {
        return { safe: false, reason: "chunk was deleted after this change was approved", liveHtml: null };
      }
      if (live !== change.afterHtml) {
        return {
          safe: false,
          reason: "chunk content has changed since this change was approved",
          liveHtml: live,
        };
      }
      return { safe: true, patch: { kind: "restore", chunkId: change.chunkId, html: change.beforeHtml } };
    }

    case "create": {
      if (change.chunkId === null) {
        return { safe: false, reason: "malformed create change: missing chunkId", liveHtml: null };
      }
      const live = liveChunks.get(change.chunkId);
      if (live === undefined) {
        return {
          safe: false,
          reason: "chunk was already removed by a later change",
          liveHtml: null,
        };
      }
      if (live !== change.afterHtml) {
        return {
          safe: false,
          reason: "chunk was edited after this change was approved",
          liveHtml: live,
        };
      }
      return { safe: true, patch: { kind: "remove", chunkId: change.chunkId } };
    }

    case "delete": {
      if (change.chunkId === null || change.beforeHtml === null) {
        return { safe: false, reason: "malformed delete change: missing chunkId or beforeHtml", liveHtml: null };
      }
      const live = liveChunks.get(change.chunkId);
      if (live !== undefined) {
        return {
          safe: false,
          reason: "a chunk with this id exists again — possibly re-created by a later change",
          liveHtml: live,
        };
      }
      return {
        safe: true,
        patch: {
          kind: "reinsert",
          chunkId: change.chunkId,
          html: change.beforeHtml,
          insertAfterChunkId: change.insertAfterChunkId,
        },
      };
    }
  }
}

/**
 * Apply a RevertPatch to a chunk map, returning a new map (never mutates
 * its argument). This is a pure, in-memory operation used by tests and by
 * the caller to compute the resulting document HTML before sending it back
 * to SuperDocs — it does not call the network itself.
 */
export function applyRevertPatch(
  chunks: ReadonlyMap<string, string>,
  patch: RevertPatch
): Map<string, string> {
  switch (patch.kind) {
    case "restore": {
      const next = new Map(chunks);
      next.set(patch.chunkId, patch.html);
      return next;
    }
    case "remove": {
      const next = new Map(chunks);
      next.delete(patch.chunkId);
      return next;
    }
    case "reinsert": {
      // Rebuild preserving document order: everything up to and including
      // the anchor, then the reinserted chunk, then the rest — rather than
      // just appending, which would silently reorder the document.
      const rebuilt = new Map<string, string>();
      if (patch.insertAfterChunkId === null) {
        rebuilt.set(patch.chunkId, patch.html);
        for (const [id, html] of chunks) rebuilt.set(id, html);
        return rebuilt;
      }
      for (const [id, html] of chunks) {
        rebuilt.set(id, html);
        if (id === patch.insertAfterChunkId) {
          rebuilt.set(patch.chunkId, patch.html);
        }
      }
      if (!rebuilt.has(patch.chunkId)) {
        // Anchor no longer exists either — append rather than drop the
        // content silently.
        rebuilt.set(patch.chunkId, patch.html);
      }
      return rebuilt;
    }
  }
}
