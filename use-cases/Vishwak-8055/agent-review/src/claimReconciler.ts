import type { ChunkDiffEntry } from "./chunkDiff";
import type { Change, NormalizedTurnEvent, ReconciliationVerdict } from "./types";

/**
 * Best-effort, fully transparent classifier for "does this reply read like
 * the agent believes it completed a document edit?" Deliberately NOT an LLM
 * call — the brief explicitly forbids using a model as the source of truth
 * for actual execution, and that prohibition extends to using one just to
 * grade the claim, since a model judging its own (or a peer's) claim is the
 * same failure mode one step removed. This is a small, readable keyword
 * heuristic instead: imperfect by nature, which is exactly why the UI always
 * shows the raw claim text next to the objective diff rather than only this
 * verdict (see docs/IMPLEMENTATION_PLAN.md §6.2).
 */
export function looksLikeCompletedEditClaim(replyText: string): boolean {
  const text = replyText.toLowerCase();

  const hedgeOrRefusalMarkers = [
    "couldn't find", "could not find", "don't see", "do not see",
    "unable to", "not sure", "which section", "no such section",
    "already satisfies", "nothing needed", "no changes needed",
    "did you mean", "can you clarify", "could you clarify",
  ];
  if (hedgeOrRefusalMarkers.some((m) => text.includes(m))) return false;

  // A reply dominated by a question is analysis/clarification, not a claim.
  const questionMarks = (text.match(/\?/g) ?? []).length;
  const sentenceEnders = (text.match(/[.!?]/g) ?? []).length;
  if (sentenceEnders > 0 && questionMarks / sentenceEnders > 0.5) return false;

  const completedEditMarkers = [
    "i've updated", "i've added", "i've changed", "i've removed",
    "i've replaced", "i've rewritten", "i've fixed", "i've inserted",
    "i've deleted", "i've restructured", "updated the", "added a",
    "added the", "changed the", "removed the", "replaced the",
    "rewrote the", "fixed the", "inserted a", "deleted the", "done.",
  ];
  return completedEditMarkers.some((m) => text.includes(m));
}

export interface ReconciliationResult {
  verdict: ReconciliationVerdict;
  changes: Change[];
}

/**
 * Reconcile one turn's claim against its objective chunk diff.
 *
 * When the diff is non-empty, one `Change` is produced per diff entry — all
 * sharing the turn's verdict, since a real mutation happened and can be
 * reviewed on its own merits regardless of how well the prose described it.
 *
 * When the diff is EMPTY, no `Change` is produced at all — there is nothing
 * to approve, reject, or revert, and manufacturing a placeholder Change here
 * would be exactly the "fake successful change" the brief's acceptance test
 * 2 forbids. The verdict alone (`claimed_not_observed` or `no_claim`) is
 * still returned so the caller can persist an audit warning even though no
 * Change exists to attach it to.
 */
export function reconcileTurn(
  turn: NormalizedTurnEvent,
  diff: ChunkDiffEntry[],
  now: () => string = () => new Date().toISOString()
): ReconciliationResult {
  if (diff.length === 0) {
    const verdict: ReconciliationVerdict = looksLikeCompletedEditClaim(turn.claimedResultText)
      ? "claimed_not_observed"
      : "no_claim";
    return { verdict, changes: [] };
  }

  // A real mutation happened. `wasBillable` corroborates it (SuperDocs
  // itself only bills a turn that actually modified the document), so a
  // non-empty diff with `wasBillable: false` is an internal inconsistency
  // worth flagging as `conflicting` rather than silently trusting the diff.
  const verdict: ReconciliationVerdict = turn.wasBillable ? "match" : "conflicting";

  const timestamp = now();
  const changes: Change[] = diff.map((entry, index) => ({
    id: `${turn.turnId}:${entry.chunkId ?? `create-${index}`}`,
    turnId: turn.turnId,
    documentId: turn.documentId,
    chunkId: entry.chunkId,
    operation: entry.operation,
    source: "auto_apply",
    sourceJobId: null,
    insertAfterChunkId: entry.insertAfterChunkId,
    beforeHtml: entry.beforeHtml,
    afterHtml: entry.afterHtml,
    status: "proposed",
    reconciliation: verdict,
    aiExplanation: null, // populated separately for HITL-sourced changes
    createdAt: timestamp,
    updatedAt: timestamp,
    decidedBy: null,
    decidedAt: null,
  }));

  return { verdict, changes };
}
