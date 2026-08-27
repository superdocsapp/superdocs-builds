import { randomUUID } from "node:crypto";
import {
  buildSurgicalMessage,
  buildWholeDocumentMessage,
  checkScope,
  htmlToText,
  toDocumentHtml,
  type ScopeReport
} from "../shared/selection.js";
import { countTextTokens, measure } from "../shared/tokens.js";
import type {
  DocumentSnapshot,
  JobWork,
  Measurement,
  ProposedChange,
  Selection,
  WholeDocumentRun
} from "../shared/types.js";
import type { ModelTier } from "./config.js";
import {
  decideChange,
  pendingChanges,
  reportedTokens,
  startEdit,
  waitForJob,
  type Job,
  type PendingChange
} from "./superdocs.js";

/**
 * The two operations TokenScope measures, and the rule that makes them
 * comparable.
 *
 * Both run in a **fresh session**. That is deliberate: `cumulative_tokens`
 * reflects the session's agent context, so a session that has already taken a
 * turn reports a figure carrying that turn with it. One session per measurement
 * means the number attributed to an operation is that operation's own, and the
 * surgical and whole-document figures are arrived at the same way.
 */

function freshSessionId(kind: "surgical" | "wholedoc"): string {
  return `tokenscope-${kind}-${randomUUID().slice(0, 12)}`;
}

function toProposedChange(change: PendingChange): ProposedChange {
  const oldHtml = change.old_html ?? "";
  const newHtml = change.new_html ?? "";

  return {
    changeId: change.change_id,
    chunkId: change.chunk_id ?? "",
    operation: change.operation ?? "edit",
    oldHtml,
    newHtml,
    oldText: htmlToText(oldHtml),
    newText: htmlToText(newHtml),
    explanation: change.ai_explanation ?? ""
  };
}

/**
 * What the job had to write, counted from the changes it returned.
 *
 * This is the number that stays honest at every document size. `new_html` is the
 * text SuperDocs actually emitted, so tokenizing it measures the output the
 * operation required - one paragraph for a surgical edit, the whole document for
 * a regeneration - without depending on a provider counter.
 */
function workOf(changes: ProposedChange[]): JobWork {
  const output = changes.reduce((sum, change) => sum + countTextTokens(change.newText), 0);

  return {
    sectionsChanged: changes.length,
    output: {
      tokens: output,
      source: "tokenized",
      method: "tokenized from the text SuperDocs returned for every section it changed on this job"
    }
  };
}

/**
 * What SuperDocs said the job cost, or null.
 *
 * `metadata.cumulative_tokens` is absent on some jobs - it was missing from the
 * 300-page run in the benchmark. Absent means "SuperDocs reported no number",
 * which is not zero and is not something to substitute a guess for. The caller
 * gets null and the UI says so.
 */
function reportedCost(job: Job): number | null {
  return reportedTokens(job) ?? null;
}

export interface SurgicalRewrite {
  sessionId: string;
  jobId: string;
  reply: string;
  changes: ProposedChange[];
  scope: ScopeReport;
  measurement: Measurement;
  work: JobWork;
  elapsedMs: number;
}

export interface RewriteOptions {
  document: DocumentSnapshot;
  selection: Selection;
  instruction: string;
  modelTier?: ModelTier;
  /**
   * How long to wait for the job. The pane keeps the default because someone is
   * sitting in front of it; the benchmark passes a much larger budget because a
   * 300-page regeneration is measured in tens of minutes and the number is the
   * whole point of running it.
   */
  timeoutMs?: number;
  onProgress?: (progress: number, status: string) => void;
}

/**
 * Rewrite the selection, and measure what it cost.
 *
 * Nothing is applied here. The job is started in ask_every_time mode and stops
 * at `awaiting_approval`; the proposed changes are returned for the user to look
 * at, and the document is untouched until `applyChange` is called.
 */
export async function rewriteSelection(options: RewriteOptions): Promise<SurgicalRewrite> {
  const sessionId = freshSessionId("surgical");
  const startedAt = Date.now();

  const { jobId } = await startEdit({
    sessionId,
    message: buildSurgicalMessage(options.selection, options.instruction),
    documentHtml: toDocumentHtml(options.document),
    ...(options.modelTier === undefined ? {} : { modelTier: options.modelTier })
  });

  const job = await waitForJob(jobId, {
    ...(options.timeoutMs === undefined ? {} : { timeoutMs: options.timeoutMs }),
    ...(options.onProgress === undefined
      ? {}
      : {
          onProgress: (j: Job) => options.onProgress?.(j.progress ?? 0, j.status)
        })
  });

  const changes = pendingChanges(job).map(toProposedChange);
  const scope = checkScope(changes, options.document, options.selection);
  const work = workOf(changes);

  return {
    sessionId,
    jobId,
    reply: replyOf(job),
    changes,
    scope,
    measurement: measure({
      document: options.document,
      selection: options.selection,
      surgicalWork: work,
      reportedSurgicalTokens: reportedCost(job)
    }),
    work,
    elapsedMs: Date.now() - startedAt
  };
}

/**
 * Run the counterfactual for real.
 *
 * Regenerating the whole document is the thing this product argues against, so
 * the number attached to it should not be something we asserted. This performs
 * the regeneration as a genuine SuperDocs job, in a throwaway session, on a copy
 * of the document, and reads the same `cumulative_tokens` field off it. The
 * user's document and session are not involved and nothing is ever approved.
 */
export async function measureWholeDocument(options: {
  document: DocumentSnapshot;
  instruction: string;
  modelTier?: ModelTier;
  timeoutMs?: number;
  onProgress?: (progress: number, status: string) => void;
}): Promise<WholeDocumentRun> {
  const sessionId = freshSessionId("wholedoc");
  const startedAt = Date.now();

  const { jobId } = await startEdit({
    sessionId,
    message: buildWholeDocumentMessage(options.instruction),
    documentHtml: toDocumentHtml(options.document),
    ...(options.modelTier === undefined ? {} : { modelTier: options.modelTier })
  });

  const job = await waitForJob(jobId, {
    ...(options.timeoutMs === undefined ? {} : { timeoutMs: options.timeoutMs }),
    ...(options.onProgress === undefined
      ? {}
      : { onProgress: (j: Job) => options.onProgress?.(j.progress ?? 0, j.status) })
  });

  return {
    sessionId,
    jobId,
    reportedTokens: reportedCost(job),
    work: workOf(pendingChanges(job).map(toProposedChange)),
    elapsedMs: Date.now() - startedAt
  };
}

/** Apply one change the user chose. The only call that mutates the document. */
export async function applyChange(options: {
  sessionId: string;
  jobId: string;
  changeId: string;
}): Promise<{ applied: true }> {
  await decideChange({ ...options, approved: true });
  return { applied: true };
}

function replyOf(job: Job): string {
  const result = job.result;

  if (result !== null && typeof result === "object" && "response" in result) {
    const response = (result as { response?: unknown }).response;
    if (typeof response === "string") return response;
  }

  return "";
}
