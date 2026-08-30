/**
 * Core domain types for the SuperDocs Agent Review workspace.
 *
 * These are intentionally decoupled from both the VS Code API and the raw
 * SuperDocs HTTP response shapes. `src/superdocsClient.ts` is responsible
 * for translating real API responses into `NormalizedTurnEvent`s; nothing
 * downstream of that boundary knows or cares which coding agent, or which
 * SuperDocs transport (REST poll, SSE, HITL payload), produced an event.
 */

export type ChangeOperation = "edit" | "create" | "delete";

export type ChangeStatus =
  | "proposed"
  | "approved"
  | "rejected"
  | "reverted"
  | "conflicted"
  | "failed"
  | "superseded";

export type ReconciliationVerdict =
  | "match"
  | "partial"
  | "conflicting"
  | "claimed_not_observed"
  | "no_claim";

/** One turn (one user message + one assistant reply) discovered on a SuperDocs session. */
export interface NormalizedTurnEvent {
  turnId: string; // `${sessionId}:${turnIndex}`
  sessionId: string;
  turnIndex: number;
  documentId: string;
  clientType: string; // "unknown" unless SuperDocs exposes caller identity
  claimedIntentText: string;
  claimedResultText: string;
  beforeHtml: string;
  afterHtml: string;
  wasBillable: boolean;
  opsCharged: number;
  timestamp: string;
  correlationId: string; // job_id when known, else turnId
}

/** One chunk-level document mutation, first-class and independently reviewable. */
/**
 * Where a Change came from — determines what "reject" has to do.
 * `auto_apply`: SuperDocs already wrote this to the live document before we
 *   ever saw it (the default path, §3.3). "Proposed" here means "already
 *   live, awaiting our sign-off" — reject must therefore *undo* it, using
 *   the same chunk-scoped patch machinery as revert.
 * `hitl`: SuperDocs is holding this change unapplied, waiting on a decision
 *   (`approval_mode: "ask_every_time"`). Reject here means "deny it" via
 *   SuperDocs's own endpoint — nothing was ever written, so there's nothing
 *   to undo.
 */
export type ChangeSource = "auto_apply" | "hitl";

export interface Change {
  id: string;
  turnId: string;
  documentId: string;
  chunkId: string | null; // null only for a `create` awaiting a chunk id
  operation: ChangeOperation;
  source: ChangeSource;
  beforeHtml: string | null;
  afterHtml: string | null;
  /**
   * For `create`: where the chunk was inserted. Also needed to safely
   * *revert* a `delete` (re-inserting requires an anchor), so it's carried
   * on every operation type rather than only `create`, and left `null`
   * when genuinely unknown/inapplicable (e.g. an `edit`, which never moves
   * the chunk).
   */
  insertAfterChunkId: string | null;
  /**
   * The SuperDocs job this change came from, when `source === "hitl"` —
   * needed to call SuperDocs's own approve/deny endpoint later, so it's
   * captured at ingestion time rather than requiring every caller of
   * approve()/reject() to separately track and re-supply it. Always `null`
   * for `auto_apply` changes, which don't need one.
   */
  sourceJobId: string | null;
  status: ChangeStatus;
  reconciliation: ReconciliationVerdict;
  aiExplanation: string | null;
  createdAt: string;
  updatedAt: string;
  decidedBy: string | null;
  decidedAt: string | null;
}

/** One user message + one assistant reply — captured once per turn so the UI can show request/claim/actual as three distinct things, not conflate them. */
export interface TurnRecord {
  turnId: string;
  sessionId: string;
  documentId: string;
  clientType: string;
  claimedIntentText: string;
  claimedResultText: string;
  timestamp: string;
}

export interface AuditRecord {
  id: string;
  changeId: string;
  turnId: string;
  who: string;
  what: string;
  when: string;
  documentId: string;
  chunkId: string | null;
  claim: string;
  actual: string;
  decision: "approved" | "rejected" | "reverted" | null;
  decidedBy: string | null;
  decidedAt: string | null;
  /**
   * Content snapshots, not version identifiers — SuperDocs's actual version/
   * checkpoint IDs (`checkpoint_id`, `turn_index`) are a separate, not-yet-
   * wired concept (see docs/GAP_ANALYSIS.md). Naming these `...Version`
   * previously implied a version-tracking guarantee this field never
   * provided; they are the raw before/after HTML this audit row concerns.
   */
  beforeContent: string | null;
  afterContent: string | null;
}
