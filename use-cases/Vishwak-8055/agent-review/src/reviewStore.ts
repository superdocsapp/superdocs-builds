import { AuditLog, nextAuditId } from "./auditLog";
import { reconcileTurn } from "./claimReconciler";
import type { ChunkDiffEntry } from "./chunkDiff";
import { applyTransition, IllegalTransitionError } from "./changeModel";
import type { PersistenceBackend } from "./persistence";
import { applyRevertPatch, planRevert, type RevertPatch } from "./revertEngine";
import type { AuditRecord, Change, NormalizedTurnEvent, ReconciliationVerdict, TurnRecord } from "./types";

/**
 * The extension-host-owned boundary to real SuperDocs network calls. The
 * review engine depends only on this narrow port, not on `SuperDocsClient`
 * directly — so every decision path in this file is unit-testable against a
 * fake, with zero network or vscode dependency (the engine is not the UI,
 * and business logic should not require a live service to test).
 */
/**
 * A `SuperDocsSideEffects.applyPatch` implementation throws this — never a
 * plain `Error` — when it must refuse to write a patch back at all (as
 * opposed to a transient failure like a network error, which the caller
 * can simply retry). `ReviewStore` catches this specifically and reports a
 * conflict rather than leaving the Change's on-disk status inconsistent
 * with reality, or silently treating a real infra failure as a content
 * conflict.
 */
export class WriteBackRefusedError extends Error {}

export interface SuperDocsSideEffects {
  /** Approve or deny a still-pending HITL change at the SuperDocs level. Never called for auto_apply changes — there is nothing pending to decide. */
  decideHitlChange(args: {
    sessionId: string;
    jobId: string;
    changeId: string;
    approved: boolean;
    feedback?: string;
  }): Promise<void>;
  /** Apply a chunk-scoped undo patch. Used both to reject an already-applied auto_apply change and to revert an approved one — the safety check is identical either way. */
  applyPatch(args: { sessionId: string; documentId: string; patch: RevertPatch }): Promise<void>;
}

export interface DecisionResult {
  change: Change;
  conflict?: { reason: string; liveHtml: string | null };
}

export interface IngestResult {
  verdict: ReconciliationVerdict;
  changes: Change[];
  alreadyIngested: boolean;
}

interface HitlPendingChangeInput {
  changeId: string;
  chunkId: string | null;
  operation: Change["operation"];
  oldHtml: string | null;
  newHtml: string | null;
  explanation: string;
  insertAfterChunkId: string | null;
}

const CHANGE_PREFIX = "change:";
const TURN_RECORD_PREFIX = "turn-record:";
const AUTO_APPLY_TURN_MARKER_PREFIX = "turn-ingested:auto:";
const HITL_TURN_MARKER_PREFIX = "turn-ingested:hitl:";

interface AutoApplyTurnMarker {
  changeIds: string[];
  verdict: ReconciliationVerdict;
}

export class ReviewStore {
  private readonly audit: AuditLog;

  constructor(
    private readonly backend: PersistenceBackend,
    private readonly sideEffects: SuperDocsSideEffects,
    private readonly now: () => string = () => new Date().toISOString()
  ) {
    this.audit = new AuditLog(backend);
  }

  // ---------------------------------------------------------------- reads

  getChange(id: string): Change | undefined {
    return this.backend.get<Change>(`${CHANGE_PREFIX}${id}`);
  }

  listAllChanges(): Change[] {
    return this.backend
      .listKeys(CHANGE_PREFIX)
      .map((k) => this.backend.get<Change>(k))
      .filter((c): c is Change => c !== undefined);
  }

  listChangesForTurn(turnId: string): Change[] {
    return this.listAllChanges()
      .filter((c) => c.turnId === turnId)
      .sort((a, b) => a.id.localeCompare(b.id));
  }

  auditTrail(): AuditRecord[] {
    return this.audit.all();
  }

  getTurnRecord(turnId: string): TurnRecord | undefined {
    return this.backend.get<TurnRecord>(`${TURN_RECORD_PREFIX}${turnId}`);
  }

  private saveTurnRecord(turn: NormalizedTurnEvent): void {
    const record: TurnRecord = {
      turnId: turn.turnId,
      sessionId: turn.sessionId,
      documentId: turn.documentId,
      clientType: turn.clientType,
      claimedIntentText: turn.claimedIntentText,
      claimedResultText: turn.claimedResultText,
      timestamp: turn.timestamp,
    };
    this.backend.set(`${TURN_RECORD_PREFIX}${turn.turnId}`, record);
  }

  // ------------------------------------------------------------ ingestion

  /**
   * Idempotent: re-ingesting an already-seen `turn.turnId` returns the
   * previously computed result rather than creating duplicate Changes or
   * audit rows (mandatory scenario: duplicate event -> one logical change).
   */
  ingestAutoApplyTurn(turn: NormalizedTurnEvent, diff: ChunkDiffEntry[]): IngestResult {
    const markerKey = `${AUTO_APPLY_TURN_MARKER_PREFIX}${turn.turnId}`;
    const existing = this.backend.get<AutoApplyTurnMarker>(markerKey);
    if (existing) {
      return {
        verdict: existing.verdict,
        changes: existing.changeIds.map((id) => this.getChange(id)).filter((c): c is Change => c !== undefined),
        alreadyIngested: true,
      };
    }

    const { verdict, changes } = reconcileTurn(turn, diff, this.now);
    this.saveTurnRecord(turn);

    for (const change of changes) {
      this.supersedePriorPendingChangeForSameChunk(change);
      this.saveChange(change);
      this.audit.append(
        this.buildAuditRecord(change, { claim: turn.claimedResultText, who: turn.clientType })
      );
    }

    if (changes.length === 0) {
      // Nothing to attach this to — record it anyway so a claimed-but-not-
      // observed turn is auditable even without a Change object to hang it on.
      this.audit.append({
        id: nextAuditId(this.now),
        changeId: `${turn.turnId}:no-change`,
        turnId: turn.turnId,
        who: turn.clientType,
        what:
          verdict === "claimed_not_observed"
            ? "turn's reply reads like a completed edit, but no chunk-level diff was observed"
            : "turn produced no document mutation",
        when: this.now(),
        documentId: turn.documentId,
        chunkId: null,
        claim: turn.claimedResultText,
        actual: "no chunk-level diff between before/after snapshots",
        decision: null,
        decidedBy: null,
        decidedAt: null,
        beforeContent: null,
        afterContent: null,
      });
    }

    this.backend.set<AutoApplyTurnMarker>(markerKey, { changeIds: changes.map((c) => c.id), verdict });
    return { verdict, changes, alreadyIngested: false };
  }

  /**
   * HITL pending changes arrive already structurally diffed by SuperDocs —
   * no reconciliation needed, just adoption into the same Change shape so
   * the rest of the system (state machine, audit, UI) never has to branch
   * on where a Change came from.
   */
  ingestHitlPendingChanges(turn: NormalizedTurnEvent, pending: HitlPendingChangeInput[]): Change[] {
    const markerKey = `${HITL_TURN_MARKER_PREFIX}${turn.turnId}`;
    const existing = this.backend.get<string[]>(markerKey);
    if (existing) {
      return existing.map((id) => this.getChange(id)).filter((c): c is Change => c !== undefined);
    }
    this.saveTurnRecord(turn);

    const created: Change[] = [];
    const timestamp = this.now();
    for (const p of pending) {
      const change: Change = {
        id: `${turn.turnId}:${p.changeId}`,
        turnId: turn.turnId,
        documentId: turn.documentId,
        chunkId: p.chunkId,
        operation: p.operation,
        source: "hitl",
        sourceJobId: turn.correlationId,
        insertAfterChunkId: p.insertAfterChunkId,
        beforeHtml: p.oldHtml,
        afterHtml: p.newHtml,
        status: "proposed",
        // SuperDocs proposed exactly this structural diff itself — its own
        // claim and its own "actual" are definitionally the same record, so
        // there's no separate reconciliation question the way there is for
        // the auto-apply path (implementation plan §6.2).
        reconciliation: "match",
        aiExplanation: p.explanation,
        createdAt: timestamp,
        updatedAt: timestamp,
        decidedBy: null,
        decidedAt: null,
      };
      this.saveChange(change);
      this.audit.append(this.buildAuditRecord(change, { claim: p.explanation, who: turn.clientType }));
      created.push(change);
    }
    this.backend.set(markerKey, created.map((c) => c.id));
    return created;
  }

  // ------------------------------------------------------------ decisions

  async approve(changeId: string, by: string, context: { sessionId: string }): Promise<DecisionResult> {
    const change = this.requireChange(changeId);
    if (change.status === "approved") return { change }; // double-submit: safe no-op, no duplicate side effect

    if (change.source === "hitl") {
      if (!change.sourceJobId) {
        throw new Error(`HITL change ${change.id} is missing its sourceJobId — cannot approve at the SuperDocs level`);
      }
      await this.sideEffects.decideHitlChange({
        sessionId: context.sessionId,
        jobId: change.sourceJobId,
        changeId: change.id,
        approved: true,
      });
    }
    // auto_apply changes are already live in the document — approving is a
    // pure sign-off with no network call, which is exactly why it's safe to
    // do before the HITL side effect above rather than after: if the HITL
    // call throws, we never reach here, so we never show "approved" for an
    // operation that didn't actually succeed.

    const approved = applyTransition(change, { type: "approve", by, at: this.now() });
    this.saveChange(approved);
    this.audit.append(this.buildAuditRecord(approved, { decision: "approved", decidedBy: by, who: by }));
    return { change: approved };
  }

  async reject(
    changeId: string,
    by: string,
    context: { sessionId: string; liveChunks?: ReadonlyMap<string, string> },
    reason?: string
  ): Promise<DecisionResult> {
    const change = this.requireChange(changeId);
    if (change.status === "rejected") return { change };

    if (change.source === "hitl") {
      if (!change.sourceJobId) {
        throw new Error(`HITL change ${change.id} is missing its sourceJobId — cannot deny at the SuperDocs level`);
      }
      await this.sideEffects.decideHitlChange({
        sessionId: context.sessionId,
        jobId: change.sourceJobId,
        changeId: change.id,
        approved: false,
        ...(reason === undefined ? {} : { feedback: reason }),
      });
      const rejected = applyTransition(change, { type: "reject", by, at: this.now() });
      this.saveChange(rejected);
      this.audit.append(
        this.buildAuditRecord(rejected, { claim: reason ?? undefined, decision: "rejected", decidedBy: by, who: by })
      );
      return { change: rejected };
    }

    // auto_apply: this change is already live in the document, so rejecting
    // it means undoing it — the exact same content-safety question revert
    // has to answer, so it reuses planRevert/applyPatch rather than a
    // second implementation of "is this still safe to touch."
    if (!context.liveChunks) {
      throw new Error("rejecting an auto-apply change requires a live chunk snapshot");
    }
    const plan = planRevert(change, context.liveChunks);
    if (!plan.safe) {
      const conflicted = applyTransition(change, { type: "markConflicted", at: this.now() });
      this.saveChange(conflicted);
      this.audit.append(this.buildAuditRecord(conflicted, { claim: plan.reason, who: "system" }));
      return { change: conflicted, conflict: { reason: plan.reason, liveHtml: plan.liveHtml } };
    }
    try {
      await this.sideEffects.applyPatch({ sessionId: context.sessionId, documentId: change.documentId, patch: plan.patch });
    } catch (err) {
      return this.handleWriteBackFailure(change, err);
    }
    const rejected = applyTransition(change, { type: "reject", by, at: this.now() });
    this.saveChange(rejected);
    this.audit.append(
      this.buildAuditRecord(rejected, { claim: reason ?? undefined, decision: "rejected", decidedBy: by, who: by })
    );
    return { change: rejected };
  }

  /**
   * Independent per-change revert: only ever touches `changeId`'s own
   * chunk. If a later, independent change has since touched that same
   * chunk, this returns a conflict instead of guessing — see
   * revertEngine.planRevert.
   */
  async revert(
    changeId: string,
    by: string,
    context: { sessionId: string; liveChunks: ReadonlyMap<string, string> }
  ): Promise<DecisionResult> {
    const change = this.requireChange(changeId);
    if (change.status === "reverted") return { change };
    if (change.status !== "approved") {
      throw new IllegalTransitionError(change.status, "revert");
    }

    const plan = planRevert(change, context.liveChunks);
    if (!plan.safe) {
      const conflicted = applyTransition(change, { type: "markConflicted", at: this.now() });
      this.saveChange(conflicted);
      this.audit.append(this.buildAuditRecord(conflicted, { claim: plan.reason, who: "system" }));
      return { change: conflicted, conflict: { reason: plan.reason, liveHtml: plan.liveHtml } };
    }
    try {
      await this.sideEffects.applyPatch({ sessionId: context.sessionId, documentId: change.documentId, patch: plan.patch });
    } catch (err) {
      return this.handleWriteBackFailure(change, err);
    }
    const reverted = applyTransition(change, { type: "revert", by, at: this.now() });
    this.saveChange(reverted);
    this.audit.append(this.buildAuditRecord(reverted, { decision: "reverted", decidedBy: by, who: by }));
    return { change: reverted };
  }

  resolveConflict(changeId: string, resolution: "approved" | "rejected", by: string): Change {
    const change = this.requireChange(changeId);
    const resolved = applyTransition(change, { type: "resolveConflict", resolution, by, at: this.now() });
    this.saveChange(resolved);
    this.audit.append(
      this.buildAuditRecord(resolved, {
        claim: "manually resolved by reviewer after a revert/approve conflict",
        decision: resolution,
        decidedBy: by,
        who: by,
      })
    );
    return resolved;
  }

  // ------------------------------------------------------------ internals

  private supersedePriorPendingChangeForSameChunk(newChange: Change): void {
    if (newChange.chunkId === null) return; // can't safely correlate creates without an assigned id
    const prior = this.listAllChanges().find(
      (c) =>
        c.status === "proposed" &&
        c.chunkId === newChange.chunkId &&
        c.documentId === newChange.documentId &&
        c.turnId !== newChange.turnId
    );
    if (!prior) return;
    const superseded = applyTransition(prior, { type: "supersede", at: this.now() });
    this.saveChange(superseded);
    this.audit.append(
      this.buildAuditRecord(superseded, {
        claim: "automatically superseded — a later turn touched the same chunk before this proposal was decided",
        who: "system",
      })
    );
  }

  private handleWriteBackFailure(change: Change, err: unknown): DecisionResult {
    if (!(err instanceof WriteBackRefusedError)) {
      throw err; // transient/infra failure: on-disk status is still accurate, let the caller retry
    }
    const conflicted = applyTransition(change, { type: "markConflicted", at: this.now() });
    this.saveChange(conflicted);
    this.audit.append(this.buildAuditRecord(conflicted, { claim: err.message, who: "system" }));
    return { change: conflicted, conflict: { reason: err.message, liveHtml: null } };
  }

  private requireChange(id: string): Change {
    const change = this.getChange(id);
    if (!change) throw new Error(`No such change: ${id}`);
    return change;
  }

  private saveChange(change: Change): void {
    this.backend.set(`${CHANGE_PREFIX}${change.id}`, change);
  }

  private buildAuditRecord(
    change: Change,
    opts: { claim?: string | undefined; decision?: AuditRecord["decision"]; decidedBy?: string; who: string }
  ): AuditRecord {
    return {
      id: nextAuditId(this.now),
      changeId: change.id,
      turnId: change.turnId,
      who: opts.who,
      what: `${change.operation} on chunk ${change.chunkId ?? "(new)"}`,
      when: this.now(),
      documentId: change.documentId,
      chunkId: change.chunkId,
      claim: opts.claim ?? change.aiExplanation ?? "",
      actual: change.afterHtml ? "chunk content changed" : "chunk removed",
      decision: opts.decision ?? null,
      decidedBy: opts.decidedBy ?? null,
      decidedAt: opts.decision ? this.now() : null,
      beforeContent: change.beforeHtml,
      afterContent: change.afterHtml,
    };
  }
}

/** Convenience re-export so callers applying a returned patch don't need a separate import. */
export { applyRevertPatch };
