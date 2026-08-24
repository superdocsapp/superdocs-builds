import type { FrozenDocumentPreview, FrozenPreviewBlock, RunSummary, SourceRegistration } from "./api";
import { isDocRelayBackupName } from "./import-state";
import type { WorkspaceState } from "./workspace-state";
import { isVerifiedWriteSuccess } from "./write-back-state";

export const NEW_DOCUMENT_EVENT = "docrelay:new-document";
export const OPEN_RECENT_DOCUMENT_EVENT = "docrelay:open-recent-document";
export const ACTIVE_DOCUMENT_EVENT = "docrelay:active-document";

export type RecentDocumentSelection = {
  fileId: string;
  name: string;
  mimeType: string;
};

let queuedRecentDocument: RecentDocumentSelection | null = null;

export function requestOpenRecentDocument(file: RecentDocumentSelection): void {
  queuedRecentDocument = file;
  if (typeof window === "undefined") return;
  window.dispatchEvent(new CustomEvent<RecentDocumentSelection>(OPEN_RECENT_DOCUMENT_EVENT, { detail: file }));
}

export function peekQueuedRecentDocument(): RecentDocumentSelection | null {
  return queuedRecentDocument;
}

export function takeQueuedRecentDocument(): RecentDocumentSelection | null {
  const file = queuedRecentDocument;
  queuedRecentDocument = null;
  return file;
}

export type ActiveDocumentDetail = {
  providerFileId: string | null;
  /** Title of the open document, so the sidebar can name it immediately. */
  name?: string | null;
};

export function setActiveDocumentId(
  providerFileId: string | null,
  name?: string | null,
): void {
  if (typeof window === "undefined") return;
  window.dispatchEvent(
    new CustomEvent<ActiveDocumentDetail>(ACTIVE_DOCUMENT_EVENT, {
      detail: { providerFileId, name: providerFileId ? name ?? null : null },
    }),
  );
}

export type ComposerKeyIntent = "submit" | "newline" | null;

export type UserInstructionTurn = {
  id: string;
  role: "user";
  text: string;
  status: "pending" | "accepted" | "failed";
  runId?: string;
  verifiedWrite?: VerifiedWriteEvidence;
  persistedEvent?: PersistedWorkflowEvent;
  error?: string;
};

export type PersistedWorkflowEvent =
  | { kind: "verified" }
  | { kind: "review"; changeCount: number }
  | { kind: "ready"; changeCount: number }
  | { kind: "conflict" }
  | { kind: "attention"; code: string | null }
  | { kind: "terminal"; status: "unsupported" | "failed" | "cancelled" | "skipped" | "expired" | "completed" };

export type DocumentConversationProjection = {
  runs: RunSummary[];
  turns: UserInstructionTurn[];
  activeRunId: string | null;
  canContinue: boolean;
};

export type VerifiedWriteEvidence = {
  runId: string;
  fileId: string;
  backupCreated: boolean;
  backupVerified: boolean;
  writeApplied: boolean;
  structurallyVerified: true;
};

export function canSubmitComposer(text: string, busy: boolean): boolean {
  return text.trim().length > 0 && !busy;
}

export function composerEnterIntent(event: {
  key: string;
  shiftKey: boolean;
}): ComposerKeyIntent {
  if (event.key !== "Enter") return null;
  return event.shiftKey ? "newline" : "submit";
}

export function startRunRequest(source: SourceRegistration, instruction: string) {
  return {
    source_id: source.source.source_id,
    baseline_capture_id: source.baseline.capture_id,
    instruction: instruction.trim(),
  };
}

export function googleDocsUrl(fileId: string): string {
  return `https://docs.google.com/document/d/${encodeURIComponent(fileId)}/edit`;
}

export function truncateRevision(value: string, head = 6, tail = 3): string {
  if (value.length <= head + tail + 1) return value;
  return `${value.slice(0, head)}…${value.slice(-tail)}`;
}

export function appendPendingInstruction(
  existing: UserInstructionTurn[],
  text: string,
  id: string,
): UserInstructionTurn[] {
  return [...existing, { id, role: "user", text, status: "pending" }];
}

export function acceptInstruction(
  existing: UserInstructionTurn[],
  id: string,
  runId?: string,
): UserInstructionTurn[] {
  return existing.map((turn) => (
    turn.id === id
      ? { ...turn, status: "accepted" as const, ...(runId ? { runId } : {}) }
      : turn
  ));
}

export function recordVerifiedWrite(
  existing: UserInstructionTurn[],
  evidence: VerifiedWriteEvidence,
): UserInstructionTurn[] {
  return existing.map((turn) => (
    turn.runId === evidence.runId ? { ...turn, verifiedWrite: evidence } : turn
  ));
}

export function failInstruction(
  existing: UserInstructionTurn[],
  id: string,
  error: string,
): UserInstructionTurn[] {
  return existing.map((turn) => (
    turn.id === id ? { ...turn, status: "failed" as const, error } : turn
  ));
}

const TERMINAL_RUN_STATES = new Set<RunSummary["workflow_state"]>([
  "SUCCEEDED",
  "CONFLICT",
  "UNSUPPORTED",
  "SKIPPED",
  "EXPIRED",
  "COMMIT_OUTCOME_UNKNOWN",
  "VERIFICATION_FAILED",
  "FAILED",
  "CANCELLED",
]);

const CONFIRMED_NO_WRITE_TERMINAL_STATES = new Set<RunSummary["workflow_state"]>([
  "UNSUPPORTED",
  "SKIPPED",
  "EXPIRED",
  "FAILED",
  "CANCELLED",
]);

function hasUncertainOutcomeCode(code: string | null): boolean {
  return code?.includes("UNKNOWN") === true || code?.includes("UNAVAILABLE") === true;
}

/** A terminal summary with no WritePlan cannot have entered Google write-back. */
export function hasConfirmedNoWriteOutcome(run: RunSummary): boolean {
  return CONFIRMED_NO_WRITE_TERMINAL_STATES.has(run.workflow_state)
    && run.write_back_status === "NOT_READY"
    && run.external_effects_unknown === 0
    && !hasUncertainOutcomeCode(run.last_error_code);
}

export function isActiveRunSummary(run: RunSummary): boolean {
  return !TERMINAL_RUN_STATES.has(run.workflow_state);
}

function runTimestamp(run: RunSummary, field: "created_at" | "updated_at"): number {
  const parsed = Date.parse(run[field]);
  return Number.isFinite(parsed) ? parsed : 0;
}

function persistedEventFromRun(run: RunSummary): PersistedWorkflowEvent {
  if (run.write_back_status === "WRITE_VERIFIED" && run.verification_status === "PASSED") {
    return { kind: "verified" };
  }
  if (run.workflow_state === "CONFLICT" || run.write_back_status === "CONFLICT") {
    return { kind: "conflict" };
  }
  if (
    run.workflow_state === "COMMIT_OUTCOME_UNKNOWN"
    || run.workflow_state === "VERIFICATION_FAILED"
    || run.write_back_status === "UNKNOWN"
    || run.write_back_status === "ATTENTION"
    || run.write_back_status === "VERIFICATION_FAILED"
  ) {
    return { kind: "attention", code: run.last_error_code };
  }
  if (run.review_status === "AWAITING_DECISIONS" || run.workflow_state === "AWAITING_REVIEW") {
    return { kind: "review", changeCount: run.proposal_count };
  }
  if (
    run.dry_run_status === "READY"
    || run.workflow_state === "REVIEWED_EXPORT_READY"
    || run.workflow_state === "READY_TO_COMMIT"
    || run.workflow_state === "PREVIEW_READY"
    || run.write_back_status === "READY"
    || run.write_back_status === "WRITE_AUTHORIZATION_REQUIRED"
  ) {
    return { kind: "ready", changeCount: run.proposal_count };
  }
  if (run.workflow_state === "UNSUPPORTED") return { kind: "terminal", status: "unsupported" };
  if (run.workflow_state === "FAILED") return { kind: "terminal", status: "failed" };
  if (run.workflow_state === "CANCELLED") return { kind: "terminal", status: "cancelled" };
  if (run.workflow_state === "SKIPPED") return { kind: "terminal", status: "skipped" };
  if (run.workflow_state === "EXPIRED") return { kind: "terminal", status: "expired" };
  if (run.workflow_state === "SUCCEEDED") return { kind: "terminal", status: "completed" };
  return { kind: "attention", code: run.last_error_code };
}

/** Projects immutable runs for one real Google document into a stable chronological thread. */
export function documentConversationFromRuns(
  runs: RunSummary[],
  providerFileId: string,
): DocumentConversationProjection {
  const deduplicated = new Map<string, RunSummary>();
  for (const run of runs) {
    if (run.provider_file_id !== providerFileId || isDocRelayBackupName(run.document_name)) continue;
    const existing = deduplicated.get(run.run_id);
    if (!existing || runTimestamp(run, "updated_at") > runTimestamp(existing, "updated_at")) {
      deduplicated.set(run.run_id, run);
    }
  }

  const ordered = [...deduplicated.values()].sort((left, right) => (
    runTimestamp(left, "created_at") - runTimestamp(right, "created_at")
    || left.run_id.localeCompare(right.run_id)
  ));
  const latest = ordered.at(-1) ?? null;
  const activeRunId = ordered.findLast(isActiveRunSummary)?.run_id ?? null;
  const turns = ordered.flatMap((run): UserInstructionTurn[] => {
    const instruction = run.instruction?.trim();
    if (!instruction) return [];
    return [{
      id: run.run_id,
      role: "user",
      text: instruction,
      status: "accepted",
      runId: run.run_id,
      ...(run.run_id === activeRunId ? {} : { persistedEvent: persistedEventFromRun(run) }),
    }];
  });

  return {
    runs: ordered,
    turns,
    activeRunId,
    canContinue: activeRunId === null && (
      latest === null
      || (latest.write_back_status === "WRITE_VERIFIED" && latest.verification_status === "PASSED")
      || hasConfirmedNoWriteOutcome(latest)
    ),
  };
}

export function frozenPreviewBlocks(
  preview: FrozenDocumentPreview | null | undefined,
): FrozenPreviewBlock[] | null {
  if (!preview?.available) return null;
  const blocks = preview.blocks.filter((block) => block.text.trim().length > 0);
  return blocks.length > 0 ? blocks : null;
}

export function workbenchSource(state: WorkspaceState): SourceRegistration | null {
  if (state.stage === "source" || state.stage === "importing") return null;
  if ("source" in state && state.source) return state.source;
  return null;
}

export const PROCESSING_STEP_LABELS = [
  "Reading source",
  "Preparing SuperDocs session",
  "Analyzing instruction",
  "Preparing proposals",
] as const;

export type ProcessingStepState = "complete" | "current" | "idle";

export type ProcessingStep = {
  label: (typeof PROCESSING_STEP_LABELS)[number];
  state: ProcessingStepState;
};

/** Maps durable run state onto the compact processing checklist. No fake progress. */
export function processingActiveStepIndex(state: string): number {
  if (state === "QUEUED") return 0;
  if (state === "BASELINING") return 1;
  return 2;
}

export function processingStepsFromRunState(state: string): ProcessingStep[] {
  const active = processingActiveStepIndex(state);
  return PROCESSING_STEP_LABELS.map((label, index) => ({
    label,
    state: index < active ? "complete" : index === active ? "current" : "idle",
  }));
}

export function workbenchStateLabel(state: WorkspaceState): string | undefined {
  switch (state.stage) {
    case "edit":
    case "processing":
      return "Active";
    case "review":
      return "Review";
    case "dry-run":
      return state.writing ? "Writing" : "Ready";
    case "write-result":
      if (state.result.status === "CONFLICT") return "Conflict";
      if (
        state.result.status === "ATTENTION"
        || state.result.status === "VERIFICATION_FAILED"
        || state.result.status === "FAILED"
      ) {
        return "Needs attention";
      }
      if (isVerifiedWriteSuccess(state.result.status, state.result.structurally_verified)) {
        return "Verified";
      }
      return "Write-back";
    case "unsupported":
    case "error":
      return "Needs attention";
    default:
      return undefined;
  }
}

/**
 * Contextual review presentation.
 *
 * The surrounding sentence is only ever taken from the frozen canonical
 * baseline preview that DocRelay already captured. Nothing is fetched live and
 * nothing is invented: when the exact old text cannot be located exactly once
 * in the frozen baseline, callers fall back to the raw proposal spans.
 */

const CONTEXT_MAX_CHARACTERS = 260;

export interface ChangedSpan {
  oldStart: number;
  oldEnd: number;
  newStart: number;
  newEnd: number;
}

/** Character offsets of the minimal differing region between two strings. */
export function changedSpan(oldText: string, newText: string): ChangedSpan {
  let prefix = 0;
  const maxPrefix = Math.min(oldText.length, newText.length);
  while (prefix < maxPrefix && oldText[prefix] === newText[prefix]) prefix += 1;

  let suffix = 0;
  const maxSuffix = Math.min(oldText.length - prefix, newText.length - prefix);
  while (
    suffix < maxSuffix
    && oldText[oldText.length - 1 - suffix] === newText[newText.length - 1 - suffix]
  ) {
    suffix += 1;
  }

  const trimmed = (text: string, start: number, end: number): [number, number] => {
    let from = start;
    let to = end;
    while (from < to && /\s/.test(text[from])) from += 1;
    while (to > from && /\s/.test(text[to - 1])) to -= 1;
    return [from, to];
  };

  const [oldStart, oldEnd] = trimmed(oldText, prefix, oldText.length - suffix);
  const [newStart, newEnd] = trimmed(newText, prefix, newText.length - suffix);
  return { oldStart, oldEnd, newStart, newEnd };
}

export interface ContextualChange {
  /** Surrounding baseline sentence with the original wording. */
  beforeText: string;
  /** The same sentence with the proposed wording substituted. */
  afterText: string;
  beforeHighlight: [number, number] | null;
  afterHighlight: [number, number] | null;
  /** Real heading from the frozen structure, when one precedes the match. */
  heading: string | null;
  /** Location of the untouched baseline span, for the document marker. */
  location: { blockIndex: number; start: number; end: number } | null;
  /** True when the sentence came from the frozen baseline, not the raw spans. */
  contextual: boolean;
}

function sentenceBounds(text: string, start: number, end: number): [number, number] {
  let from = 0;
  for (let index = start - 1; index >= 0; index -= 1) {
    if (/[.!?]/.test(text[index]) && (index + 1 >= text.length || /\s/.test(text[index + 1]))) {
      from = index + 1;
      break;
    }
  }
  let to = text.length;
  for (let index = end; index < text.length; index += 1) {
    if (/[.!?]/.test(text[index]) && (index + 1 >= text.length || /\s/.test(text[index + 1]))) {
      to = index + 1;
      break;
    }
  }
  while (from < start && /\s/.test(text[from])) from += 1;
  while (to > end && /\s/.test(text[to - 1])) to -= 1;

  // Never let one very long paragraph flood the conversation column.
  if (to - from > CONTEXT_MAX_CHARACTERS) {
    const slack = Math.max(0, CONTEXT_MAX_CHARACTERS - (end - start));
    from = Math.max(from, start - Math.floor(slack / 2));
    to = Math.min(to, end + Math.ceil(slack / 2));
  }
  return [from, to];
}

function locateUnique(
  blocks: FrozenPreviewBlock[],
  needle: string,
): { blockIndex: number; offset: number } | null {
  let found: { blockIndex: number; offset: number } | null = null;
  for (let blockIndex = 0; blockIndex < blocks.length; blockIndex += 1) {
    const text = blocks[blockIndex].text;
    let from = 0;
    for (;;) {
      const offset = text.indexOf(needle, from);
      if (offset < 0) break;
      if (found) return null; // ambiguous location: not trustworthy
      found = { blockIndex, offset };
      from = offset + Math.max(1, needle.length);
    }
  }
  return found;
}

function precedingHeading(blocks: FrozenPreviewBlock[], blockIndex: number): string | null {
  for (let index = blockIndex; index >= 0; index -= 1) {
    if (blocks[index].kind !== "heading") continue;
    const style = blocks[index].named_style;
    if (style === "TITLE" || style === "SUBTITLE") return null;
    const heading = blocks[index].text.trim();
    return heading.length > 0 && heading.length <= 60 ? heading : null;
  }
  return null;
}

/**
 * Builds the review presentation for one replacement, preferring the frozen
 * baseline sentence and degrading safely to the exact proposal spans.
 */
export function contextualChange(
  blocks: FrozenPreviewBlock[] | null,
  oldText: string | null,
  newText: string | null,
): ContextualChange | null {
  if (!oldText && !newText) return null;
  const span = oldText && newText ? changedSpan(oldText, newText) : null;

  const fallback: ContextualChange = {
    beforeText: oldText ?? "",
    afterText: newText ?? "",
    beforeHighlight: span && span.oldEnd > span.oldStart ? [span.oldStart, span.oldEnd] : null,
    afterHighlight: span && span.newEnd > span.newStart ? [span.newStart, span.newEnd] : null,
    heading: null,
    location: null,
    contextual: false,
  };

  if (!blocks || !oldText || !newText) return fallback;

  const match = locateUnique(blocks, oldText);
  if (!match) return fallback;

  const blockText = blocks[match.blockIndex].text;
  const matchEnd = match.offset + oldText.length;
  const [from, to] = sentenceBounds(blockText, match.offset, matchEnd);
  const relative = match.offset - from;
  const beforeText = blockText.slice(from, to);
  if (!beforeText.includes(oldText)) return fallback;

  const afterText = `${beforeText.slice(0, relative)}${newText}${beforeText.slice(relative + oldText.length)}`;

  return {
    beforeText,
    afterText,
    beforeHighlight: span && span.oldEnd > span.oldStart
      ? [relative + span.oldStart, relative + span.oldEnd]
      : null,
    afterHighlight: span && span.newEnd > span.newStart
      ? [relative + span.newStart, relative + span.newEnd]
      : null,
    heading: precedingHeading(blocks, match.blockIndex),
    location: { blockIndex: match.blockIndex, start: match.offset, end: matchEnd },
    contextual: true,
  };
}

const SAFETY_CHECK_LABELS: Record<string, string> = {
  "approved immutable review decision": "Review decision recorded",
  "exact persisted baseline revision and native snapshot hash": "Exact source revision matched",
  "one unique ordinary body paragraph and one plain text run": "Unique location found",
  "exact internal ASCII preimage with equal UTF-16 length": "Source text exactly matched",
  "exact internal contiguous ASCII preimage": "Source text exactly matched",
  "minimum delete-and-insert range guarded by requiredRevisionId": "Revision guard prepared",
  "independent non-overlapping replacements on the same frozen revision":
    "Approved changes do not overlap",
};

/**
 * Human labels for the safety evidence the dry run actually reported. Nothing
 * is added beyond the backend's own `why_safe` list, except the backup step
 * the write pipeline always performs first.
 */
export function normalizedSafetyChecks(checks: string[]): string[] {
  const result = checks.map((check) => SAFETY_CHECK_LABELS[check] ?? check);
  if (!result.some((check) => check.toLowerCase().includes("backup"))) {
    result.push("Backup will be created first");
  }
  return result;
}

export interface DocumentReviewMark {
  blockIndex: number;
  start: number;
  end: number;
}

/** Trustworthy baseline locations for the pending proposals, if any. */
export function documentReviewMarks(
  blocks: FrozenPreviewBlock[] | null,
  changes: Array<{ oldText: string | null; newText: string | null }>,
): DocumentReviewMark[] {
  if (!blocks) return [];
  const marks: DocumentReviewMark[] = [];
  for (const change of changes) {
    const context = contextualChange(blocks, change.oldText, change.newText);
    if (context?.location) marks.push(context.location);
  }
  return marks;
}
