/**
 * SuperDocs REST client.
 *
 * Grounded against the live API reference at docs.superdocs.app (fetched
 * 2026-08-17; see TASK2_REQUIREMENTS.md for what was verified against
 * primary docs vs. inferred). Two integration details the reference
 * specifically calls out as easy to get wrong are handled explicitly here,
 * not left as an exercise for the caller:
 *
 *   1. The SSE `proposed_change_batch` event's payload is double-JSON-
 *      encoded: `event.data` parses to an object whose `.content` field is
 *      ITSELF a JSON string that must be parsed again to reach
 *      `{ type, batch_id, batch_total, changes }`. See
 *      parseProposedChangeBatchEvent and its dedicated test.
 *
 *   2. A batch call to POST /v1/chat/{session_id}/approve requires a
 *      top-level `approved` field even when every entry in `changes` has
 *      its own -- omitting it is a 422. buildApprovePayload always includes
 *      it, so this can't be gotten wrong by a caller of this module.
 *
 * This client defaults to the async + polling path for chat, not the SSE
 * stream: for an unattended backend QA pipeline (this use case), polling
 * GET /v1/jobs/{job_id} is simpler and just as correct, and the docs
 * confirm it's a fully supported alternative to SSE, not a degraded one.
 * The SSE parsing helper is still implemented and tested, since the task
 * document specifically flags the double-encoding gotcha and the
 * `/stream` endpoint is where it's documented to occur.
 */

export type SuperDocsModelTier = "core" | "turbo" | "pro" | "max";
export type SuperDocsThinkingDepth = "fast" | "balanced" | "deep";

export interface SuperDocsClientOptions {
  apiKey?: string; // defaults to process.env.SUPERDOCS_API_KEY
  baseUrl?: string; // defaults to https://api.superdocs.app
  fetchImpl?: typeof fetch;
}

export class SuperDocsApiError extends Error {
  constructor(
    message: string,
    public readonly status: number,
    public readonly body: string,
  ) {
    super(message);
    this.name = "SuperDocsApiError";
  }
}

export class SuperDocsAuthError extends SuperDocsApiError {}
export class SuperDocsRateLimitError extends SuperDocsApiError {
  constructor(
    message: string,
    status: number,
    body: string,
    public readonly retryAfterSeconds: number | null,
  ) {
    super(message, status, body);
    this.name = "SuperDocsRateLimitError";
  }
}
/** 504s on large documents are documented as "still processing," not necessarily failure -- callers should treat this as retryable, not fatal. */
export class SuperDocsTimeoutError extends SuperDocsApiError {}
export class SuperDocsValidationError extends SuperDocsApiError {}

export interface UploadResult {
  html: string;
  sessionId: string;
  filename: string;
  chunksCount: number;
  versionId: string;
}

export interface ChatResult {
  updatedHtml: string | null;
  usage: { monthlyUsed?: number; monthlyLimit?: number; quotaExhausted?: boolean } | null;
  raw: unknown;
}

export type JobStatus = "pending" | "in_progress" | "awaiting_approval" | "completed" | "failed" | "cancelled";

export interface JobResult {
  jobId: string;
  status: JobStatus;
  pendingChanges: ProposedChange[];
  updatedHtml: string | null;
  raw: unknown;
}

export interface ProposedChange {
  changeId: string;
  chunkId: string;
  [key: string]: unknown;
}

/** Raw API shape uses snake_case; normalizes to the camelCase ProposedChange this client exposes everywhere else. */
function normalizeProposedChange(raw: Record<string, unknown>): ProposedChange {
  const { change_id, chunk_id, ...rest } = raw;
  return { changeId: String(change_id), chunkId: String(chunk_id), ...rest };
}

export interface ProposedChangeBatch {
  type: string;
  batchId: string;
  batchTotal: number;
  changes: ProposedChange[];
}

/**
 * Implements gotcha #1: `rawEventData` is the SSE `event.data` string,
 * already valid JSON on its own -- but the `.content` field inside it is a
 * SECOND, independently JSON-encoded string. Parse twice, not once.
 */
export function parseProposedChangeBatchEvent(rawEventData: string): ProposedChangeBatch {
  const outer = JSON.parse(rawEventData) as { content: string };
  if (typeof outer.content !== "string") {
    throw new Error("parseProposedChangeBatchEvent: expected outer.content to be a JSON-encoded string, got " + typeof outer.content);
  }
  const inner = JSON.parse(outer.content) as { type: string; batch_id: string; batch_total: number; changes: Record<string, unknown>[] };
  return { type: inner.type, batchId: inner.batch_id, batchTotal: inner.batch_total, changes: inner.changes.map(normalizeProposedChange) };
}

export interface ApproveDecision {
  changeId: string;
  approved: boolean;
  feedback?: string;
}

/**
 * Implements gotcha #2: always sets a top-level `approved` even for a
 * batch of per-change decisions. When decisions are mixed (some approved,
 * some rejected), the top-level flag is set to true -- it gates the
 * request as a whole being processed, not a shortcut that overrides the
 * per-change flags below it.
 */
export function buildApprovePayload(decisions: ApproveDecision[]): { approved: boolean; changes: Array<{ change_id: string; approved: boolean; feedback?: string }> } {
  return {
    approved: true,
    changes: decisions.map((d) => ({ change_id: d.changeId, approved: d.approved, ...(d.feedback ? { feedback: d.feedback } : {}) })),
  };
}

export class SuperDocsClient {
  private readonly apiKey: string | undefined;
  private readonly baseUrl: string;
  private readonly fetchImpl: typeof fetch;

  constructor(options: SuperDocsClientOptions = {}) {
    this.apiKey = options.apiKey ?? process.env.SUPERDOCS_API_KEY;
    this.baseUrl = options.baseUrl ?? "https://api.superdocs.app";
    this.fetchImpl = options.fetchImpl ?? fetch;
  }

  private requireApiKey(): string {
    if (!this.apiKey) {
      throw new Error("SuperDocsClient: no API key. Set SUPERDOCS_API_KEY in the environment (see .env.example), or pass { apiKey } explicitly.");
    }
    return this.apiKey;
  }

  private async request(path: string, init: RequestInit): Promise<Response> {
    const apiKey = this.requireApiKey();
    const response = await this.fetchImpl(`${this.baseUrl}${path}`, {
      ...init,
      headers: { Authorization: `Bearer ${apiKey}`, ...(init.headers ?? {}) },
    });

    if (response.ok) return response;

    const bodyText = await response.text().catch(() => "");
    const message = `SuperDocs API ${response.status} ${response.statusText} on ${path}: ${bodyText.slice(0, 500)}`;
    if (response.status === 401 || response.status === 403) throw new SuperDocsAuthError(message, response.status, bodyText);
    if (response.status === 429) {
      const retryAfterHeader = response.headers.get("retry-after");
      throw new SuperDocsRateLimitError(message, response.status, bodyText, retryAfterHeader ? Number(retryAfterHeader) : null);
    }
    if (response.status === 422) throw new SuperDocsValidationError(message, response.status, bodyText);
    if (response.status === 504) throw new SuperDocsTimeoutError(message, response.status, bodyText);
    throw new SuperDocsApiError(message, response.status, bodyText);
  }

  private async requestJson<T>(path: string, init: RequestInit): Promise<T> {
    const response = await this.request(path, init);
    return (await response.json()) as T;
  }

  async uploadDocument(file: Blob, filename: string, sessionId?: string): Promise<UploadResult> {
    const form = new FormData();
    form.append("file", file, filename);
    if (sessionId) form.append("session_id", sessionId);
    const data = await this.requestJson<{ html: string; session_id: string; filename: string; chunks_count: number; version_id: string }>(
      "/v1/documents/upload",
      { method: "POST", body: form },
    );
    return { html: data.html, sessionId: data.session_id, filename: data.filename, chunksCount: data.chunks_count, versionId: data.version_id };
  }

  async renameDocument(documentId: string, title: string): Promise<{ status: string }> {
    return this.requestJson<{ status: string }>(`/v1/documents/${encodeURIComponent(documentId)}`, {
      method: "PATCH",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ title }),
    });
  }

  async chat(params: { message: string; sessionId: string; documentHtml?: string; modelTier?: SuperDocsModelTier; thinkingDepth?: SuperDocsThinkingDepth }): Promise<ChatResult> {
    const data = await this.requestJson<{
      data?: { document_changes?: { updated_html?: string }; usage?: { monthly_used?: number; monthly_limit?: number; quota_exhausted?: boolean } };
    }>("/v1/chat", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({
        message: params.message,
        session_id: params.sessionId,
        ...(params.documentHtml ? { document_html: params.documentHtml } : {}),
        ...(params.modelTier ? { model_tier: params.modelTier } : {}),
        ...(params.thinkingDepth ? { thinking_depth: params.thinkingDepth } : {}),
      }),
    });
    return {
      updatedHtml: data.data?.document_changes?.updated_html ?? null,
      usage: data.data?.usage
        ? { monthlyUsed: data.data.usage.monthly_used, monthlyLimit: data.data.usage.monthly_limit, quotaExhausted: data.data.usage.quota_exhausted }
        : null,
      raw: data,
    };
  }

  async chatAsync(params: {
    message: string;
    sessionId: string;
    documentHtml?: string;
    approvalMode: "ask_every_time" | "approve_all";
    modelTier?: SuperDocsModelTier;
    thinkingDepth?: SuperDocsThinkingDepth;
  }): Promise<{ jobId: string }> {
    const data = await this.requestJson<{ job_id: string }>("/v1/chat/async", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({
        message: params.message,
        session_id: params.sessionId,
        approval_mode: params.approvalMode,
        ...(params.documentHtml ? { document_html: params.documentHtml } : {}),
        ...(params.modelTier ? { model_tier: params.modelTier } : {}),
        ...(params.thinkingDepth ? { thinking_depth: params.thinkingDepth } : {}),
      }),
    });
    return { jobId: data.job_id };
  }

  async getJob(jobId: string): Promise<JobResult> {
    const data = await this.requestJson<{
      job_id: string;
      status: JobStatus;
      metadata?: { pending_changes?: Record<string, unknown>[]; updated_html?: string };
      result?: { document_changes?: { updated_html?: string } };
    }>(`/v1/jobs/${encodeURIComponent(jobId)}`, { method: "GET" });
    return {
      jobId: data.job_id,
      status: data.status,
      pendingChanges: (data.metadata?.pending_changes ?? []).map(normalizeProposedChange),
      updatedHtml: data.metadata?.updated_html ?? data.result?.document_changes?.updated_html ?? null,
      raw: data,
    };
  }

  /**
   * Polls a job until it leaves pending/in_progress. Long documents are
   * documented to take anywhere from thirty seconds to several minutes --
   * this defaults to a generous ceiling with linear backoff rather than a
   * short timeout that would misreport normal processing as failure.
   */
  async pollJobUntilSettled(jobId: string, options: { maxWaitMs?: number; intervalMs?: number } = {}): Promise<JobResult> {
    const maxWaitMs = options.maxWaitMs ?? 10 * 60 * 1000;
    const intervalMs = options.intervalMs ?? 2000;
    const deadline = Date.now() + maxWaitMs;
    let lastResult: JobResult;
    do {
      lastResult = await this.getJob(jobId);
      if (lastResult.status !== "pending" && lastResult.status !== "in_progress") return lastResult;
      await new Promise((resolve) => setTimeout(resolve, intervalMs));
    } while (Date.now() < deadline);
    return lastResult; // caller decides how to treat a still-pending job at the ceiling; we don't invent a "failed" status SuperDocs never reported
  }

  async approveChanges(sessionId: string, decisions: ApproveDecision[]): Promise<{ status: string }> {
    return this.requestJson<{ status: string }>(`/v1/chat/${encodeURIComponent(sessionId)}/approve`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(buildApprovePayload(decisions)),
    });
  }

  async probeAuth(): Promise<{ authenticated: boolean; status: number }> {
    const apiKey = this.requireApiKey();
    const probeId = `probe-${Date.now().toString(36)}`;
    const response = await this.fetchImpl(`${this.baseUrl}/v1/jobs/${probeId}`, {
      method: "GET",
      headers: { Authorization: `Bearer ${apiKey}` },
    });
    if (response.status === 401 || response.status === 403) return { authenticated: false, status: response.status };
    // A random job id returning 404 is the expected authenticated response;
    // 200/other 2xx also proves the credential is accepted.
    return { authenticated: response.ok || response.status === 404, status: response.status };
  }

  async exportDocument(params: { sessionId: string; format: "docx" | "pdf" | "html" | "markdown" | "txt" }): Promise<Blob> {
    const response = await this.request("/v1/documents/export", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ session_id: params.sessionId, format: params.format }),
    });
    return response.blob();
  }
}
