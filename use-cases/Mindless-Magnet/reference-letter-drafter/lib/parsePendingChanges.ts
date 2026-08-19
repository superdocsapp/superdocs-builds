import type { JobStatusResponse, PendingChange } from "./types";

/**
 * SuperDocs delivers proposed changes as a JSON-encoded STRING inside the job
 * metadata, and the final result as a real object. Their integration notes call
 * missing that second parse the single most common reason integrators see empty
 * diff cards where every field is `undefined`.
 *
 * So this is written to accept the shape rather than assume it: already an
 * array, a JSON string of an array, a double-encoded string, an object with the
 * array under a key. Anything it cannot make sense of returns an empty list and
 * a stated reason — never a half-populated change with undefined fields, which
 * would render as an approve button over a blank diff. Approving a blank diff
 * is worse than showing an error.
 *
 * This function is pure and has no imports beyond types, which is why it is the
 * most heavily tested thing in the repo.
 */

const MAX_UNWRAP_DEPTH = 3;

export interface ParsedChanges {
  changes: PendingChange[];
  /** Set when parsing failed or produced nothing usable. */
  problem?: string;
}

function unwrap(value: unknown, depth = 0): unknown {
  if (typeof value !== "string" || depth >= MAX_UNWRAP_DEPTH) return value;
  const trimmed = value.trim();
  if (!trimmed.startsWith("[") && !trimmed.startsWith("{") && !trimmed.startsWith('"')) return value;
  try {
    return unwrap(JSON.parse(trimmed), depth + 1);
  } catch {
    return value;
  }
}

/** Keys SuperDocs has been observed to nest the array under. */
const CANDIDATE_KEYS = ["pending_changes", "changes", "proposed_changes", "items"];

function toArray(value: unknown): unknown[] | null {
  if (Array.isArray(value)) return value;
  if (value && typeof value === "object") {
    for (const key of CANDIDATE_KEYS) {
      const nested = unwrap((value as Record<string, unknown>)[key]);
      if (Array.isArray(nested)) return nested;
    }
  }
  return null;
}

function str(value: unknown): string | undefined {
  return typeof value === "string" ? value : undefined;
}

/**
 * A change is usable only if it has an id and something to show. Without
 * `change_id` the approval cannot be routed back; without any HTML there is
 * nothing for a human to judge. Both are refusals, not defaults.
 */
function normaliseOne(raw: unknown, index: number): PendingChange | null {
  const value = unwrap(raw);
  if (!value || typeof value !== "object") return null;
  const r = value as Record<string, unknown>;

  const changeId = str(r.change_id) ?? str(r.id);
  if (!changeId) return null;

  const newHtml = str(r.new_html) ?? str(r.new_content) ?? str(r.after) ?? "";
  const oldHtml = str(r.old_html) ?? str(r.old_content) ?? str(r.before) ?? "";
  if (!newHtml && !oldHtml) return null;

  const rawOp = (str(r.operation) ?? "edit").toLowerCase();
  const operation: PendingChange["operation"] =
    rawOp === "insert" || rawOp === "delete" ? rawOp : "edit";

  return {
    change_id: changeId,
    operation,
    chunk_id: str(r.chunk_id) ?? "",
    document_id: str(r.document_id) ?? "",
    old_html: oldHtml,
    new_html: newHtml,
    ai_explanation:
      str(r.ai_explanation) ?? str(r.explanation) ?? str(r.reason) ?? `Proposed change ${index + 1}`,
    insert_after_chunk_id: str(r.insert_after_chunk_id) ?? null,
  };
}

export function parsePendingChanges(input: unknown): ParsedChanges {
  const unwrapped = unwrap(input);
  if (unwrapped === undefined || unwrapped === null || unwrapped === "") {
    return { changes: [] };
  }

  const array = toArray(unwrapped);
  if (!array) {
    return {
      changes: [],
      problem:
        "SuperDocs returned proposed changes in a shape this app does not recognise. Nothing was applied. " +
        "This is worth reporting as a bug with the job id.",
    };
  }

  const changes = array
    .map((item, i) => normaliseOne(item, i))
    .filter((change): change is PendingChange => change !== null);

  if (array.length > 0 && changes.length === 0) {
    return {
      changes: [],
      problem:
        `SuperDocs proposed ${array.length} change(s), but none carried both an id and content, so none can be ` +
        "safely reviewed. Nothing was applied.",
    };
  }

  if (changes.length < array.length) {
    return {
      changes,
      problem: `${array.length - changes.length} of ${array.length} proposed changes were malformed and are not shown.`,
    };
  }

  return { changes };
}

/** Pull the pending changes out of a job payload, wherever they are living. */
export function pendingChangesFromJob(job: JobStatusResponse | undefined): ParsedChanges {
  if (!job) return { changes: [] };
  const metadata = job.metadata as Record<string, unknown> | undefined;
  if (!metadata) return { changes: [] };
  if (metadata.awaiting_kind === "continue_prompt") return { changes: [] };
  return parsePendingChanges(metadata.pending_changes ?? metadata.changes);
}

/** The document HTML, from whichever field the job actually populated. */
export function documentHtmlFromJob(job: JobStatusResponse | undefined): string {
  if (!job) return "";
  const result = job.result as Record<string, unknown> | null | undefined;
  if (!result) return "";
  const changes = result.document_changes as Record<string, unknown> | undefined;
  return (
    (typeof changes?.updated_html === "string" ? changes.updated_html : undefined) ??
    (typeof result.updated_html === "string" ? result.updated_html : undefined) ??
    (typeof result.html === "string" ? result.html : undefined) ??
    ""
  );
}
