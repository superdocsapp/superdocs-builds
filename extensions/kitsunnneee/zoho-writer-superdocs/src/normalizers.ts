import type {
  ChangeOperation,
  JobStatus,
  NormalizedJob,
  PendingChange,
  Usage,
} from "./types";

type RecordValue = Record<string, unknown>;

const isRecord = (value: unknown): value is RecordValue =>
  typeof value === "object" && value !== null && !Array.isArray(value);

const describeShape = (value: unknown, depth = 0): string => {
  if (value === null) return "null";
  if (Array.isArray(value)) {
    if (depth >= 6) return `array(length=${value.length})`;
    return `array(length=${value.length},first=${describeShape(value[0], depth + 1)})`;
  }
  if (typeof value !== "object") return typeof value;
  if (depth >= 6) return "object";
  const record = value as RecordValue;
  const fields = Object.keys(record)
    .sort()
    .map((key) => `${key}:${describeShape(record[key], depth + 1)}`);
  return `object(${fields.join(",") || "empty"})`;
};

const FAILURE_MESSAGE_KEYS = [
  "message",
  "error_description",
  "errorMessage",
  "statusText",
  "detail",
  "description",
  "error",
  "responseText",
  "response",
  "data",
  "body",
] as const;

const readFailureMessage = (
  value: unknown,
  depth = 0,
): string | undefined => {
  if (typeof value === "string" && value.trim()) return value.trim();
  if (!isRecord(value) || depth >= 4) return undefined;
  for (const key of FAILURE_MESSAGE_KEYS) {
    const nested = readFailureMessage(value[key], depth + 1);
    if (nested !== undefined) return nested;
  }
  return undefined;
};

// Sigma rejects with plain objects rather than Errors, so the raw rejection
// would otherwise be reported as a generic failure with no detail.
export const describeFailure = (value: unknown): string => {
  if (value instanceof Error && value.message) return value.message;

  const message = readFailureMessage(value);
  const status = isRecord(value)
    ? value.status ?? value.statusCode ?? value.code
    : undefined;
  const statusText =
    typeof status === "number" || typeof status === "string"
      ? ` (status ${status})`
      : "";

  if (value === undefined || value === null) {
    return "An unexpected error occurred.";
  }
  // Sigma's messages are often a bare word such as "failed", so the structure
  // is reported alongside it to keep the panel self-sufficient for bug reports.
  const shape = describeShape(value);
  if (message) return `${message.slice(0, 300)}${statusText} [${shape}]`;
  return `Request failed${statusText}: ${shape}`;
};

// Writer wraps the selection in repeated data/content envelopes. Only these
// keys are followed, so no unrelated string elsewhere can be read as content.
const SELECTION_CONTENT_KEYS = [
  "html",
  "content",
  "text",
  "selectedContent",
  "data",
] as const;

const readSelectionString = (value: unknown, depth = 0): string | undefined => {
  if (typeof value === "string") return value;
  if (!isRecord(value) || depth >= 6) return undefined;
  for (const key of SELECTION_CONTENT_KEYS) {
    const nested = readSelectionString(value[key], depth + 1);
    if (nested !== undefined) return nested;
  }
  return undefined;
};

export const normalizeSelectedHtml = (value: unknown): string => {
  // Writer's documented response, including an empty string for no selection.
  if (typeof value === "string") return value;

  if (isRecord(value)) {
    // The live Sigma v3 event bridge can preserve its single-handler envelope.
    if (Array.isArray(value.response)) {
      const results = value.response;
      if (
        results.length === 1 &&
        isRecord(results[0]) &&
        results[0].isSuccess === true &&
        typeof results[0].response === "string"
      ) {
        return results[0].response;
      }
    }

    // Zoho Writer's live envelope carries the selection under `data`.
    const selection = readSelectionString(value.data);
    if (selection !== undefined) return selection;
  }

  // `message` is a Zoho status string, never document content, so it is the one
  // response field safe to surface when the selection cannot be read.
  const status =
    isRecord(value) && typeof value.message === "string"
      ? ` Writer said: ${value.message.slice(0, 200)}`
      : "";
  throw new Error(
    `Writer returned an unexpected selection response (${describeShape(value)}).${status}`,
  );
};

const parseJsonLayers = (value: unknown, maxDepth = 4): unknown => {
  let current = value;
  for (let depth = 0; depth < maxDepth && typeof current === "string"; depth += 1) {
    const trimmed = current.trim();
    if (!trimmed || !["{", "[", '"'].includes(trimmed[0] ?? "")) break;
    try {
      current = JSON.parse(trimmed) as unknown;
    } catch {
      break;
    }
  }
  return current;
};

const unwrapTransport = (value: unknown): unknown => {
  let current = parseJsonLayers(value);
  for (let depth = 0; depth < 4 && isRecord(current); depth += 1) {
    const next =
      current.data ??
      current.body ??
      current.responseBody ??
      current.responseText;
    if (next === undefined) break;
    current = parseJsonLayers(next);
  }
  return current;
};

const pick = (record: RecordValue | undefined, ...keys: string[]): unknown => {
  if (!record) return undefined;
  for (const key of keys) {
    if (record[key] !== undefined) return record[key];
  }
  return undefined;
};

const asRecord = (value: unknown): RecordValue | undefined => {
  const parsed = parseJsonLayers(value);
  return isRecord(parsed) ? parsed : undefined;
};

const asString = (value: unknown): string | undefined =>
  typeof value === "string" ? value : undefined;

const asNumber = (value: unknown): number | undefined =>
  typeof value === "number" && Number.isFinite(value) ? value : undefined;

const normalizeStatus = (value: unknown): JobStatus => {
  const status = asString(value)?.toLowerCase();
  if (status === "processing" || status === "running" || status === "started") {
    return "in_progress";
  }
  if (
    status === "pending" ||
    status === "in_progress" ||
    status === "awaiting_approval" ||
    status === "completed" ||
    status === "failed" ||
    status === "cancelled"
  ) {
    return status;
  }
  return "unknown";
};

const normalizeOperation = (value: unknown): ChangeOperation => {
  const operation = asString(value)?.toLowerCase();
  return operation === "edit" || operation === "create" || operation === "delete"
    ? operation
    : "unknown";
};

const normalizeChange = (value: unknown, index: number): PendingChange | null => {
  const change = asRecord(value);
  if (!change) return null;
  const id = asString(pick(change, "change_id", "changeId", "id"));
  if (!id) return null;
  return {
    id,
    operation: normalizeOperation(pick(change, "operation", "type")),
    chunkId: asString(pick(change, "chunk_id", "chunkId")),
    insertAfterChunkId: asString(
      pick(change, "insert_after_chunk_id", "insertAfterChunkId"),
    ),
    oldHtml:
      asString(pick(change, "old_html", "oldHtml", "before", "old_content")) ?? "",
    newHtml:
      asString(pick(change, "new_html", "newHtml", "after", "new_content")) ?? "",
    explanation:
      asString(pick(change, "ai_explanation", "explanation", "reason")) ??
      `Proposed change ${index + 1}`,
  };
};

const normalizeChanges = (...candidates: unknown[]): PendingChange[] => {
  for (const candidate of candidates) {
    const parsed = parseJsonLayers(candidate);
    if (!Array.isArray(parsed)) continue;
    return parsed
      .map(normalizeChange)
      .filter((change): change is PendingChange => change !== null);
  }
  return [];
};

const normalizeUsage = (value: unknown): Usage | undefined => {
  const usage = asRecord(value);
  if (!usage) return undefined;
  return {
    monthlyUsed: asNumber(pick(usage, "monthly_used", "monthlyUsed")),
    monthlyLimit: asNumber(pick(usage, "monthly_limit", "monthlyLimit")),
    monthlyRemaining: asNumber(
      pick(usage, "monthly_remaining", "monthlyRemaining"),
    ),
    operationsCharged: asNumber(pick(usage, "ops_charged", "operationsCharged")),
    wasBillable:
      typeof pick(usage, "was_billable", "wasBillable") === "boolean"
        ? (pick(usage, "was_billable", "wasBillable") as boolean)
        : undefined,
  };
};

export const normalizePollingPayload = (payload: unknown): NormalizedJob => {
  const root = asRecord(unwrapTransport(payload)) ?? {};
  const metadata = asRecord(pick(root, "metadata", "meta"));
  const result = asRecord(root.result);
  const documentChanges = asRecord(
    pick(result, "document_changes", "documentChanges"),
  );
  const changes = normalizeChanges(
    pick(metadata, "pending_changes", "pendingChanges"),
    pick(documentChanges, "pending_changes", "pendingChanges"),
    pick(root, "pending_changes", "pendingChanges"),
    pick(root, "changes"),
  );
  const usage = normalizeUsage(pick(result, "usage") ?? pick(root, "usage"));

  return {
    jobId: asString(pick(root, "job_id", "jobId")),
    sessionId:
      asString(pick(root, "session_id", "sessionId")) ??
      asString(pick(result, "session_id", "sessionId")),
    status: normalizeStatus(pick(root, "status", "state")),
    progress: asNumber(pick(root, "progress", "percent")),
    changes,
    awaitingKind: asString(pick(metadata, "awaiting_kind", "awaitingKind")),
    usage,
    updatedHtml: asString(
      pick(documentChanges, "updated_html", "updatedHtml") ??
        pick(result, "updated_html", "updatedHtml"),
    ),
    error: asString(pick(root, "error", "message")),
    raw: root,
  };
};

export const normalizeSsePayload = (payload: string): unknown[] => {
  const events: unknown[] = [];
  let dataLines: string[] = [];

  const flush = () => {
    if (dataLines.length === 0) return;
    events.push(parseJsonLayers(dataLines.join("\n")));
    dataLines = [];
  };

  for (const line of payload.replace(/\r\n/g, "\n").split("\n")) {
    if (line === "") {
      flush();
    } else if (line.startsWith("data:")) {
      dataLines.push(line.slice(5).trimStart());
    }
  }
  flush();
  return events;
};
