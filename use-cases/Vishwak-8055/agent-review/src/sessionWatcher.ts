import { diffDocumentHtml, DuplicateChunkIdError } from "./chunkDiff";
import type { PersistenceBackend } from "./persistence";
import type { ReviewStore } from "./reviewStore";
import type { JobDetail, PendingChange, SessionHistory } from "./superdocsClient";
import type { NormalizedTurnEvent } from "./types";

/** The slice of SuperDocsClient the watcher actually needs — narrow on purpose so tests don't require the real HTTP client. */
export interface SuperDocsReadPort {
  listSessions(): Promise<{ session_id: string; last_activity: string }[]>;
  listSessionJobs(sessionId: string): Promise<{ job_id: string; status: string; created_at?: string }[]>;
  getJob(jobId: string): Promise<JobDetail>;
  getSessionHistory(sessionId: string): Promise<SessionHistory>;
}

/** Thrown/detected shape of a rate-limit response, duck-typed so this module doesn't need to import SuperDocsClient's concrete error class. */
interface RateLimitLike {
  status: 429;
  retryAfterSeconds: number | null;
}
function isRateLimitError(err: unknown): err is RateLimitLike {
  return typeof err === "object" && err !== null && (err as { status?: unknown }).status === 429;
}

export interface TurnExtraction {
  turn: NormalizedTurnEvent;
  diff: ReturnType<typeof diffDocumentHtml>;
  hitlPending: PendingChange[] | null;
}

/**
 * Pure, independently testable extraction of a NormalizedTurnEvent from one
 * SuperDocs job. Deliberately isolated: `result.document_changes.updated_html`,
 * `result.response`, `result.usage`, and `metadata.pending_changes` are
 * transcribed from docs.superdocs.app (docs/IMPLEMENTATION_PLAN.md §3), but
 * this sandbox's network egress doesn't reach api.superdocs.app, so none of
 * this could be smoke-tested against a live account. If a live account's
 * job payloads turn out to be shaped differently, this is the one function
 * that needs to change — every caller downstream of it is unaffected.
 */
export function extractTurn(args: {
  job: JobDetail;
  sessionId: string;
  documentId: string;
  clientType: string;
  turnIndex: number;
  previousHtml: string;
  /** Best-effort — see docs/IMPLEMENTATION_PLAN.md §15 on session/history correlation. */
  claimedIntentText: string;
}): TurnExtraction | null {
  const { job } = args;

  if (job.status === "awaiting_approval" && job.metadata?.pending_changes) {
    return {
      turn: buildTurn(args, args.previousHtml, args.previousHtml), // nothing applied yet
      diff: [],
      hitlPending: job.metadata.pending_changes,
    };
  }

  if (job.status !== "completed") return null; // failed / cancelled / still in flight: nothing to ingest yet

  const updatedHtml = job.result?.document_changes?.updated_html ?? args.previousHtml;
  return {
    turn: buildTurn(args, args.previousHtml, updatedHtml),
    diff: diffDocumentHtml(args.previousHtml, updatedHtml),
    hitlPending: null,
  };
}

function buildTurn(
  args: { sessionId: string; documentId: string; clientType: string; turnIndex: number; claimedIntentText: string; job: JobDetail },
  beforeHtml: string,
  afterHtml: string
): NormalizedTurnEvent {
  return {
    // Identity rests on the server-assigned job_id, not this watcher's own
    // locally-computed turnIndex — a counter can drift across restarts or
    // reordering in ways a real server id cannot, and the whole point of
    // this field is that the same job can never become two logical turns.
    turnId: `${args.sessionId}:${args.job.job_id}`,
    sessionId: args.sessionId,
    turnIndex: args.turnIndex,
    documentId: args.documentId,
    clientType: args.clientType,
    claimedIntentText: args.claimedIntentText,
    claimedResultText: args.job.result?.response ?? "",
    beforeHtml,
    afterHtml,
    wasBillable: args.job.result?.usage?.was_billable ?? false,
    opsCharged: args.job.result?.usage?.ops_charged ?? 0,
    timestamp: args.job.created_at ?? new Date().toISOString(),
    correlationId: args.job.job_id,
  };
}

/**
 * Finds the user instruction that produced a given assistant reply, by
 * content match rather than by assuming this watcher's own locally-assigned
 * `turnIndex` numbering lines up with SuperDocs's own message indexing
 * (unverified from this sandbox — see docs/GAP_ANALYSIS.md). Pure and
 * independently testable. Returns "" if no match is found (e.g. history
 * hasn't caught up yet, or the reply text is empty) rather than guessing.
 */
export function findPrecedingUserInstruction(
  messages: SessionHistory["messages"],
  replyText: string
): string {
  if (!replyText) return "";
  const replyIndex = messages.findIndex((m) => m.role === "assistant" && m.content === replyText);
  if (replyIndex <= 0) return "";
  for (let i = replyIndex - 1; i >= 0; i--) {
    const m = messages[i];
    if (m?.role === "user") return m.content;
  }
  return "";
}

/**
 * Resolves the document identity for a session.
 *
 * SuperDocs's documented API distinguishes a session (`session_id`, a
 * conversation) from a File (`document_id`, the durable saved document —
 * see docs/IMPLEMENTATION_PLAN.md §3.2). A session can in principle hold
 * more than one open document. This build could not confirm, without live
 * API access, which field on a job or session response actually carries a
 * document's real `document_id` — so rather than scatter that unverified
 * assumption across the codebase, it is isolated here, in exactly one
 * place: today this returns the session id itself as a stand-in, which is
 * only correct for the common single-document-per-session case and is
 * explicitly wrong for genuine multi-document turns. When a live account
 * confirms the real field, this is the one function that needs to change —
 * every caller already treats its return value as "the document identity,"
 * not as "the session identity."
 */
function resolveDocumentId(sessionId: string): string {
  return sessionId;
}

interface SessionCursor {
  lastProcessedJobIds: string[]; // array, not Set, so it survives JSON persistence
  nextTurnIndex: number;
  lastKnownHtml: string;
  documentId: string;
}

const CURSOR_PREFIX = "watcher-cursor:";

/**
 * Polls SuperDocs for new jobs across every session reachable with the
 * configured API key and feeds newly-completed (or newly-awaiting-approval)
 * jobs into the ReviewStore. Deliberately agent-agnostic: it has no idea
 * which coding agent, if any, issued the request that produced a job — it
 * only knows a session now has a job it hasn't processed. `clientType` is
 * therefore always `"unknown"` here unless a future SuperDocs response
 * exposes caller identity (docs/IMPLEMENTATION_PLAN.md §6.1/§15).
 *
 * `documentId` is currently set equal to `sessionId` as a placeholder — the
 * real multi-document-per-session response shape was not verifiable from
 * this sandbox (no live network access), so this is explicitly NOT a
 * claim that the API guarantees a 1:1 session/document relationship. See
 * docs/GAP_ANALYSIS.md. Real multi-document support needs this fixed first.
 */
export class SessionWatcher {
  private readonly cursors = new Map<string, SessionCursor>();
  private timer: ReturnType<typeof setInterval> | null = null;
  private polling = false; // overlap guard — a slow poll must not overlap the next tick
  private pausedUntil = 0; // epoch ms; set on a 429 to honor Retry-After

  constructor(
    private readonly client: SuperDocsReadPort,
    private readonly store: ReviewStore,
    private readonly options: {
      pollIntervalMs?: number;
      onError?: (err: unknown, context: { sessionId?: string }) => void;
      persistence?: PersistenceBackend;
      now?: () => number;
    } = {}
  ) {
    if (this.options.persistence) this.loadCursors(this.options.persistence);
  }

  start(): void {
    if (this.timer) return; // already running
    const interval = this.options.pollIntervalMs ?? 4000;
    this.timer = setInterval(() => {
      void this.pollOnce().catch((err) => this.options.onError?.(err, {}));
    }, interval);
  }

  stop(): void {
    if (this.timer) clearInterval(this.timer);
    this.timer = null;
  }

  async pollOnce(): Promise<void> {
    const now = this.options.now?.() ?? Date.now();
    if (this.polling) return; // previous tick still running — never overlap
    if (now < this.pausedUntil) return; // honoring a prior 429's Retry-After

    this.polling = true;
    try {
      let sessions: { session_id: string; last_activity: string }[];
      try {
        sessions = await this.client.listSessions();
      } catch (err) {
        this.handleRateLimit(err);
        throw err;
      }

      for (const session of sessions) {
        try {
          await this.syncSession(session.session_id);
        } catch (err) {
          // One session's failure (network blip, that session's jobs list
          // erroring, a malformed job) must never block the others.
          this.handleRateLimit(err);
          this.options.onError?.(err, { sessionId: session.session_id });
        }
      }
    } finally {
      this.polling = false;
    }
  }

  private handleRateLimit(err: unknown): void {
    if (!isRateLimitError(err)) return;
    const waitMs = (err.retryAfterSeconds ?? 30) * 1000;
    this.pausedUntil = (this.options.now?.() ?? Date.now()) + waitMs;
  }

  /**
   * Establishes the correct starting point the first time a session is
   * seen — this is the fix for a real bug found in review: without it, the
   * very first job ever observed on a session would be diffed against an
   * empty document, reporting an entire pre-existing document as though
   * every chunk were newly created by the agent. Any job that is *already*
   * `completed` at first sight is pre-existing history this watcher has no
   * reliable "before" snapshot for, so it's silently accounted for
   * (marked processed, folded into the baseline) rather than reviewed.
   *
   * A job that is `awaiting_approval` at first sight is deliberately
   * *not* bootstrap-skipped: it is a real, currently-pending decision
   * regardless of when the watcher started, and HITL changes carry their
   * own accurate before/after (`old_html`/`new_html`) from SuperDocs
   * directly, so there's no empty-baseline risk for that path.
   */
  private async bootstrapCursor(
    sessionId: string,
    sortedJobs: { job_id: string; status: string; created_at?: string }[]
  ): Promise<SessionCursor> {
    const completedJobs = sortedJobs.filter((j) => j.status === "completed");
    const alreadyCompleted = completedJobs.map((j) => j.job_id);

    const history = await this.client
      .getSessionHistory(sessionId)
      .catch(() => ({ messages: [], document_state: null }) as SessionHistory);
    let baselineHtml = history.document_state?.html ?? "";

    // Session history didn't yield document state but jobs already exist —
    // fall back to the most recently completed job's own recorded result
    // rather than defaulting straight to an empty baseline.
    if (!baselineHtml && completedJobs.length > 0) {
      const lastJobSummary = completedJobs[completedJobs.length - 1];
      if (lastJobSummary) {
        const lastJob = await this.client.getJob(lastJobSummary.job_id).catch(() => null);
        baselineHtml = lastJob?.result?.document_changes?.updated_html ?? "";
      }
    }

    return {
      lastProcessedJobIds: alreadyCompleted,
      nextTurnIndex: alreadyCompleted.length + 1,
      lastKnownHtml: baselineHtml,
      documentId: resolveDocumentId(sessionId),
    };
  }

  private async syncSession(sessionId: string): Promise<void> {
    const jobs = await this.client.listSessionJobs(sessionId);
    // Never trust API return order — process in creation order so a job
    // that resolves out of order can't be diffed against the wrong
    // "previous" document snapshot.
    const sorted = [...jobs].sort((a, b) => (a.created_at ?? "").localeCompare(b.created_at ?? ""));

    let cursor = this.cursors.get(sessionId);
    if (!cursor) {
      cursor = await this.bootstrapCursor(sessionId, sorted);
      this.cursors.set(sessionId, cursor);
      this.saveCursor(sessionId, cursor);
    }

    let sessionHistory: SessionHistory | null = null; // fetched at most once per sync, only if needed
    let touchedCursor = false;

    for (const jobSummary of sorted) {
      if (cursor.lastProcessedJobIds.includes(jobSummary.job_id)) continue;

      const job = await this.client.getJob(jobSummary.job_id);

      let claimedIntentText = "";
      const replyText = job.result?.response;
      if (replyText) {
        sessionHistory ??= await this.client.getSessionHistory(sessionId).catch(() => ({ messages: [], document_state: null }));
        claimedIntentText = findPrecedingUserInstruction(sessionHistory.messages, replyText);
      }

      let extraction: ReturnType<typeof extractTurn>;
      try {
        extraction = extractTurn({
          job,
          sessionId,
          documentId: cursor.documentId,
          clientType: "unknown",
          turnIndex: cursor.nextTurnIndex,
          previousHtml: cursor.lastKnownHtml,
          claimedIntentText,
        });
      } catch (err) {
        if (err instanceof DuplicateChunkIdError) {
          // This turn cannot be safely diffed/reviewed (never silently
          // guess — see chunkDiff.ts). Report it clearly and mark the job
          // done so it doesn't retry forever. The baseline is still
          // advanced to this job's own result — not left stale — but note
          // that if the *document itself* now contains a duplicate id,
          // that contamination carries forward: a later turn's diff
          // against this baseline will also be flagged, deliberately,
          // rather than silently treated as safe just because the new
          // content looks unrelated. Recovering currently has no
          // dedicated UI action — see docs/GAP_ANALYSIS.md.
          this.options.onError?.(err, { sessionId });
          cursor.lastProcessedJobIds.push(job.job_id);
          cursor.nextTurnIndex += 1;
          const fallbackHtml = job.result?.document_changes?.updated_html;
          if (fallbackHtml !== undefined) cursor.lastKnownHtml = fallbackHtml;
          touchedCursor = true;
          continue;
        }
        throw err;
      }
      if (!extraction) continue; // job not resolved yet; try again next poll

      if (extraction.hitlPending) {
        this.store.ingestHitlPendingChanges(
          extraction.turn,
          extraction.hitlPending.map((p) => ({
            changeId: p.change_id,
            chunkId: p.chunk_id,
            operation: p.operation,
            oldHtml: p.old_html,
            newHtml: p.new_html,
            explanation: p.ai_explanation,
            insertAfterChunkId: p.insert_after_chunk_id,
          }))
        );
        // Awaiting approval: don't advance lastKnownHtml or mark the job
        // processed — re-check it on the next poll until it resolves.
        continue;
      }

      this.store.ingestAutoApplyTurn(extraction.turn, extraction.diff);
      cursor.lastProcessedJobIds.push(job.job_id);
      cursor.nextTurnIndex += 1;
      cursor.lastKnownHtml = extraction.turn.afterHtml;
      touchedCursor = true;
    }

    if (touchedCursor) this.saveCursor(sessionId, cursor);
  }

  private loadCursors(backend: PersistenceBackend): void {
    for (const key of backend.listKeys(CURSOR_PREFIX)) {
      const sessionId = key.slice(CURSOR_PREFIX.length);
      const cursor = backend.get<SessionCursor>(key);
      if (cursor) this.cursors.set(sessionId, cursor);
    }
  }

  private saveCursor(sessionId: string, cursor: SessionCursor): void {
    this.options.persistence?.set(`${CURSOR_PREFIX}${sessionId}`, cursor);
  }
}
