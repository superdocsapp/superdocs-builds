/**
 * Client for this app's own server. The server is the only thing that talks to
 * SuperDocs, so the API key never reaches the browser bundle.
 */

import type { AuditEvent, ChangeListItem, JobState, ServiceHealth, UploadResult, WriteBackResult } from "./domain";

/**
 * The server answers every failure with the same envelope, so the UI can decide
 * what to say from `code` and whether to offer a retry from `retryable` —
 * without matching on message text.
 */
export class ApiError extends Error {
  code: string;
  detail?: string | null;
  retryable: boolean;
  requestId?: string;
  data?: unknown;

  constructor(payload: {
    code?: string;
    message: string;
    detail?: string | null;
    retryable?: boolean;
    requestId?: string;
    data?: unknown;
  }) {
    super(payload.message);
    this.name = "ApiError";
    this.code = payload.code ?? "unknown";
    this.detail = payload.detail;
    this.retryable = payload.retryable ?? false;
    this.requestId = payload.requestId;
    this.data = payload.data;
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    ...init,
    headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) }
  });

  const payload = await response.json().catch(() => null);

  if (!response.ok) {
    const envelope = (payload as { error?: Record<string, unknown> })?.error;

    throw new ApiError({
      code: envelope?.code as string,
      message: (envelope?.message as string) ?? `Request failed with ${response.status}`,
      detail: envelope?.detail as string,
      retryable: envelope?.retryable as boolean,
      requestId: envelope?.requestId as string,
      data: envelope?.data
    });
  }

  return payload as T;
}

export function fetchHealth() {
  return request<ServiceHealth>("/api/health");
}

export function fetchChanges() {
  return request<{ changes: ChangeListItem[] }>("/api/changes");
}

/** SuperDocs step 1: upload the mapped ServiceNow record into a session. */
export function uploadDocument(number: string) {
  return request<UploadResult>("/api/documents/upload", {
    method: "POST",
    body: JSON.stringify({ number })
  });
}

/** SuperDocs step 2: start the edit. Changes are held for approval. */
export function startEdit(sessionId: string) {
  return request<{ jobId: string; status: string }>("/api/documents/edit", {
    method: "POST",
    body: JSON.stringify({ sessionId })
  });
}

export function fetchJob(sessionId: string, jobId: string) {
  return request<JobState>(
    `/api/documents/job/${encodeURIComponent(jobId)}?sessionId=${encodeURIComponent(sessionId)}`
  );
}

/** SuperDocs step 3: one approve/reject decision per proposed change. */
export function decideChange(input: {
  sessionId: string;
  jobId: string;
  changeId: string;
  approved: boolean;
  feedback?: string;
}) {
  return request<{ changeId: string; approved: boolean; batchComplete: boolean }>(
    "/api/documents/decide",
    { method: "POST", body: JSON.stringify(input) }
  );
}

/** Every decision in one round trip, so a batch cannot land half-applied. */
export function decideBatch(input: {
  sessionId: string;
  jobId: string;
  decisions: Array<{ changeId: string; approved: boolean }>;
}) {
  return request<{ decided: Array<{ changeId: string; approved: boolean }>; batchComplete: boolean }>(
    "/api/documents/decide-batch",
    { method: "POST", body: JSON.stringify(input) }
  );
}

/** Resolve the other kind of pause: a large edit asking whether to keep going. */
export function continueEdit(input: { sessionId: string; jobId: string; keepGoing: boolean }) {
  return request<{ keepGoing: boolean; status: string | null }>("/api/documents/continue", {
    method: "POST",
    body: JSON.stringify(input)
  });
}

/** Ask SuperDocs to redo one section, told why the first attempt was rejected. */
export function reEditChunk(input: { sessionId: string; changeId: string; feedback?: string }) {
  return request<{ chunkId: string; html: string | null; error: string | null }>(
    "/api/documents/reedit",
    { method: "POST", body: JSON.stringify(input) }
  );
}

/** Reviewer sign-off on the finished document, re-verified server-side. */
export function approveDocument(sessionId: string, reviewer?: string) {
  return request<{ approved: boolean; approvedAt: string; checksum: string }>(
    "/api/documents/approve",
    { method: "POST", body: JSON.stringify({ sessionId, reviewer }) }
  );
}

export function fetchAudit(sessionId: string) {
  return request<{
    sessionId: string;
    change: string | null;
    checksum: string | null;
    writeBack: WriteBackResult | null;
    events: AuditEvent[];
  }>(`/api/runs/${encodeURIComponent(sessionId)}/audit`);
}

/**
 * Live run updates over SSE.
 *
 * `activity` carries SuperDocs' own progress messages; `state` carries the full
 * derived run state, so the client never merges partial updates. The returned
 * function closes the stream. Callers keep polling as a fallback — a dropped
 * stream must not strand a review.
 */
export function subscribeToRun(
  sessionId: string,
  jobId: string,
  handlers: {
    onState: (state: JobState) => void;
    onActivity?: (event: { type: string; content: string; at: string }) => void;
    onDegraded?: (message: string) => void;
    onError?: (message: string) => void;
  }
) {
  const url = `/api/documents/stream?sessionId=${encodeURIComponent(sessionId)}&jobId=${encodeURIComponent(jobId)}`;
  const source = new EventSource(url);

  source.addEventListener("state", (event) => {
    try {
      handlers.onState(JSON.parse((event as MessageEvent).data) as JobState);
    } catch {
      /* a malformed frame is not worth tearing the stream down for */
    }
  });

  source.addEventListener("activity", (event) => {
    try {
      handlers.onActivity?.(JSON.parse((event as MessageEvent).data));
    } catch {
      /* ignore */
    }
  });

  source.addEventListener("degraded", (event) => {
    try {
      handlers.onDegraded?.(JSON.parse((event as MessageEvent).data).message);
    } catch {
      handlers.onDegraded?.("Live progress dropped.");
    }
  });

  // EventSource reconnects on its own; the caller's polling fallback covers
  // the window where it cannot.
  source.onerror = () => handlers.onError?.("Live progress interrupted.");

  return () => source.close();
}

/** SuperDocs step 4: export the approved document and hand the file to the browser. */
export async function exportDocument(sessionId: string, filename: string) {
  const response = await fetch("/api/documents/export", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ sessionId, format: "docx" })
  });

  if (!response.ok) {
    const payload = await response.json().catch(() => null);
    const envelope = (payload as { error?: Record<string, unknown> })?.error;

    throw new ApiError({
      code: envelope?.code as string,
      message: (envelope?.message as string) ?? "The export failed.",
      detail: envelope?.detail as string,
      retryable: envelope?.retryable as boolean,
      requestId: envelope?.requestId as string,
      data: envelope?.data
    });
  }

  const blob = await response.blob();
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  anchor.click();
  URL.revokeObjectURL(url);

  return { checksum: response.headers.get("X-Document-Checksum") };
}
