/**
 * Workflow state derivation.
 *
 * The server owns what the run "is" and what the reviewer should do next. The
 * browser renders that; it does not compute it. Keeping this in one pure module
 * means the guided rail, the SSE stream and the polling fallback cannot
 * disagree about the state of a run, and it can be tested without a network.
 */

import { FAILED_STATUSES, TERMINAL_STATUSES } from "./superdocs.js";
import { verifyPreservedValues, verifyProposedChange } from "./documentMapping.js";

/**
 * A large edit pauses to ask whether to keep going. It reports the same
 * `awaiting_approval` status as a change batch and is told apart only by this
 * field — and it is resolved by a different endpoint.
 */
export function awaitingKind(job) {
  const kind = job?.metadata?.awaiting_kind ?? job?.metadata?.awaitingKind ?? null;
  if (kind) return kind;
  if (job?.status !== "awaiting_approval") return null;

  const pending = job?.metadata?.pending_changes ?? job?.result?.document_changes?.pending_changes ?? [];
  return pending.length ? "change_batch" : "continue_prompt";
}

/** SuperDocs reports progress as free-form intermediate messages; this is the feed. */
export function readActivity(job) {
  return (job?.metadata?.intermediate_responses ?? []).map((entry, index) => ({
    sequence: entry.sequence ?? index,
    type: entry.type ?? "progress",
    content: typeof entry.content === "string" ? entry.content : JSON.stringify(entry.content ?? ""),
    at: entry.timestamp ?? null
  }));
}

/**
 * Normalize one SuperDocs job into the shape the UI consumes, verifying every
 * proposed change against the ServiceNow record on the way through.
 *
 * `run` is mutated: proposals are remembered so a later decision can be
 * re-verified server-side against the proposal as SuperDocs sent it, rather
 * than against whatever the client echoes back.
 */
export function describeJob(run, job) {
  const metadata = job.metadata ?? {};
  const documentChanges = job.result?.document_changes ?? {};
  const decided = metadata.pending_batch_decisions ?? {};
  const kind = awaitingKind(job);

  const rawChanges = metadata.pending_changes ?? documentChanges.pending_changes ?? [];

  const proposedChanges = rawChanges.map((proposed) => {
    const changeId = proposed.change_id ?? proposed.id;
    run.proposals ??= {};
    run.proposals[changeId] = proposed;

    return {
      changeId,
      chunkId: proposed.chunk_id ?? null,
      operation: proposed.operation ?? "edit",
      explanation: proposed.ai_explanation ?? null,
      before: proposed.old_html ?? null,
      after: proposed.new_html ?? null,
      decided: Object.prototype.hasOwnProperty.call(decided, changeId),
      decision: decided[changeId]?.approved ?? run.decisions?.[changeId] ?? null,
      verification: verifyProposedChange(run.change, proposed)
    };
  });

  if (documentChanges.updated_html) run.finalHtml = documentChanges.updated_html;
  if (documentChanges.version_id) run.versionId = documentChanges.version_id;

  const finished = TERMINAL_STATUSES.has(job.status);
  const failed = FAILED_STATUSES.has(job.status);
  if (finished) run.completed = !failed;

  const verification = run.finalHtml ? verifyPreservedValues(run.change, run.finalHtml) : null;
  run.finalVerification = verification;

  const undecided = proposedChanges.filter((proposal) => !proposal.decided);
  const readyToApprove = Boolean(run.completed && verification?.ok && !run.approved);
  const exportReady = Boolean(run.completed && verification?.ok && run.approved);

  const state = {
    sessionId: run.sessionId,
    status: job.status,
    progress: job.progress ?? null,
    awaitingKind: kind,
    awaitingApproval: kind === "change_batch",
    awaitingContinue: kind === "continue_prompt",
    finished,
    failed,
    summary: documentChanges.changes_summary ?? job.result?.response ?? null,
    proposedChanges,
    activity: readActivity(job),
    documentHtml: run.finalHtml ?? null,
    versionId: run.versionId ?? null,
    verification,
    approved: Boolean(run.approved),
    approvedAt: run.approvedAt ?? null,
    // Who signed off, and what they signed off on. Both live server-side, so a
    // reviewer who reloads the page still sees the attribution rather than an
    // approval with nobody's name on it.
    reviewer: run.reviewer ?? null,
    checksum: run.checksum ?? null,
    readyToApprove,
    exportReady,
    exported: Boolean(run.exportedAt),
    writeBack: run.writeBack ?? null,
    audit: run.audit ?? [],
    error: job.error ?? null
  };

  state.nextAction = nextAction(state, undecided);
  return state;
}

/**
 * The single next thing the reviewer should do.
 *
 * The whole guided experience hangs off this: the rail, the highlighted button
 * and the coaching copy all read one value, so the app can never suggest two
 * different next steps at once.
 */
export function nextAction(state, undecided) {
  if (state.failed) {
    return {
      id: "restart",
      label: "Start the run again",
      detail: "SuperDocs could not finish this edit.",
      tone: "danger"
    };
  }

  if (state.awaitingContinue) {
    return {
      id: "continue",
      label: "Let SuperDocs continue",
      detail: "The edit is large enough that SuperDocs paused to ask whether to keep going.",
      tone: "primary"
    };
  }

  const blocked = undecided.filter((proposal) => proposal.verification.verdict === "blocked");

  if (blocked.length) {
    return {
      id: "reject-blocked",
      label: `Reject ${blocked.length} blocked ${plural(blocked.length, "change")}`,
      detail: "These rewrite a value ServiceNow owns. They cannot be approved.",
      tone: "danger",
      count: blocked.length
    };
  }

  if (undecided.length) {
    return {
      id: "decide",
      label: `Decide ${undecided.length} proposed ${plural(undecided.length, "change")}`,
      detail: "Each edit needs an approve or reject before SuperDocs moves on.",
      tone: "primary",
      count: undecided.length
    };
  }

  if (!state.finished) {
    return {
      id: "wait",
      label: "SuperDocs is drafting",
      detail: "Proposed changes appear here as the model works through the document.",
      tone: "neutral"
    };
  }

  if (state.verification && !state.verification.ok) {
    const broken = state.verification.checks.filter((check) => !check.found);
    return {
      id: "blocked-final",
      label: "The document no longer matches ServiceNow",
      detail: `${broken.map((check) => check.label).join(", ")}. Export is refused.`,
      tone: "danger"
    };
  }

  if (state.readyToApprove) {
    return {
      id: "approve",
      label: "Approve the document",
      detail: "Every ServiceNow-owned value survived. Sign off to unlock export.",
      tone: "primary"
    };
  }

  if (state.exportReady && !state.exported) {
    return {
      id: "export",
      label: "Export the change record",
      detail: "SuperDocs renders the approved document and it is written back to ServiceNow.",
      tone: "primary"
    };
  }

  if (state.exported) {
    return {
      id: "done",
      label: "Run complete",
      detail: "The document was exported and recorded against the ServiceNow change.",
      tone: "success"
    };
  }

  return { id: "wait", label: "Waiting on SuperDocs", detail: null, tone: "neutral" };
}

function plural(count, word) {
  return count === 1 ? word : `${word}s`;
}
