/**
 * Running an asynchronous SuperDocs job with a human at the gate.
 *
 * The loop is deliberately boring and deliberately resumable. A job is identified
 * by `job_id`; that id, plus the session id, is everything needed to re-attach
 * after Obsidian is closed, the laptop sleeps, or the process is killed. The
 * runner never holds state that is not also on disk in the pending-job record.
 *
 * The human decision is a real gate: the runner stops at `awaiting_approval` and
 * returns. It cannot approve on its own, has no default, and no timeout that
 * silently accepts. Nothing lands in the manuscript without an explicit decision.
 */

import type { JobStatus, ProposedChange, SuperDocsClient } from "./client";
import { parseMaybeEncoded } from "./client";

export interface PendingJob {
  jobId: string;
  sessionId: string;
  /** What the user asked for, so a resumed review can explain itself. */
  instruction: string;
  startedAt: string;
  /** Hash of the manuscript the job was started against. */
  documentHash: string;
}

export type JobOutcome =
  | { kind: "awaiting_approval"; job: JobStatus; changes: ProposedChange[] }
  | { kind: "continue_prompt"; job: JobStatus }
  | { kind: "completed"; job: JobStatus }
  | { kind: "failed"; job: JobStatus; error: string }
  | { kind: "cancelled"; job: JobStatus };

export interface PollOptions {
  /** Called on every poll so a UI can show that something is still happening. */
  onTick?: (job: JobStatus, elapsedMs: number) => void;
  /** Give up after this long. Defaults to 10 minutes; book-scale edits are slow. */
  timeoutMs?: number;
  intervalMs?: number;
  sleep?: (ms: number) => Promise<void>;
  now?: () => number;
  signal?: { aborted: boolean };
}

/**
 * Poll a job until it stops needing us.
 *
 * Latency note that cost real time to learn: a large edit can run for minutes with
 * no visible progress. That is "still processing", not a crash, and the poller
 * treats it as such rather than declaring failure early.
 */
export async function pollJob(
  client: SuperDocsClient,
  jobId: string,
  opts: PollOptions = {},
): Promise<JobOutcome> {
  const sleep = opts.sleep ?? ((ms: number) => new Promise((r) => setTimeout(r, ms)));
  const now = opts.now ?? (() => Date.now());
  const timeoutMs = opts.timeoutMs ?? 10 * 60 * 1000;
  const interval = opts.intervalMs ?? 2000;
  const started = now();

  for (;;) {
    if (opts.signal?.aborted) {
      const job = await client.getJob(jobId);
      return { kind: "cancelled", job };
    }

    const job = await client.getJob(jobId);
    opts.onTick?.(job, now() - started);

    switch (job.status) {
      case "awaiting_approval": {
        // Two different pauses share this status. Branching on the wrong one
        // returns a 409 from the API, so always read awaiting_kind first.
        if (job.metadata?.awaiting_kind === "continue_prompt") {
          return { kind: "continue_prompt", job };
        }
        return { kind: "awaiting_approval", job, changes: extractPendingChanges(job) };
      }
      case "completed":
        return { kind: "completed", job };
      case "failed":
        return { kind: "failed", job, error: job.error ?? "The job failed without a reason." };
      case "cancelled":
        return { kind: "cancelled", job };
      default:
        break;
    }

    if (now() - started > timeoutMs) {
      return {
        kind: "failed",
        job,
        error: `The job was still ${job.status} after ${Math.round(
          timeoutMs / 1000,
        )}s. It has not been cancelled — reopen the review to pick it up.`,
      };
    }
    await sleep(interval);
  }
}

/**
 * Read the pending changes off a job.
 *
 * Proposed-change content arrives as a JSON-encoded string inside an already-JSON
 * response, so it needs a second parse. Skipping that is the single most common
 * reason an integration shows diff cards where every field reads `undefined`, and
 * it is why this goes through `parseMaybeEncoded` rather than a direct cast.
 */
export function extractPendingChanges(job: JobStatus): ProposedChange[] {
  const raw =
    job.metadata?.pending_changes ??
    job.result?.document_changes?.pending_changes ??
    job.result?.document_changes?.changes ??
    [];
  const parsed = parseMaybeEncoded<ProposedChange[]>(raw as unknown);
  if (!Array.isArray(parsed)) return [];
  return parsed
    .map((c) => parseMaybeEncoded<ProposedChange>(c as unknown))
    .filter((c): c is ProposedChange => Boolean(c && c.change_id));
}

/**
 * Apply approved changes to the local manuscript HTML.
 *
 * The server holds the authoritative document, but the plugin needs to show the
 * result immediately and to write it back to the vault. `updated_html` from the
 * completed job is preferred when present; this is the fallback for a partial
 * result, and it applies only the changes the human said yes to.
 */
export function applyApprovedChanges(
  html: string,
  changes: ProposedChange[],
  approvals: Map<string, boolean>,
): { html: string; applied: number; skipped: number } {
  let out = html;
  let applied = 0;
  let skipped = 0;

  for (const change of changes) {
    if (!approvals.get(change.change_id)) {
      skipped += 1;
      continue;
    }
    if (change.operation === "edit" && change.old_html && change.new_html) {
      if (out.includes(change.old_html)) {
        out = out.replace(change.old_html, change.new_html);
        applied += 1;
      } else {
        skipped += 1;
      }
      continue;
    }
    if (change.operation === "delete" && change.old_html) {
      if (out.includes(change.old_html)) {
        out = out.replace(change.old_html, "");
        applied += 1;
      } else {
        skipped += 1;
      }
      continue;
    }
    if (change.operation === "create" && change.new_html) {
      out = `${out}\n${change.new_html}`;
      applied += 1;
      continue;
    }
    skipped += 1;
  }
  return { html: out, applied, skipped };
}
