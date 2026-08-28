import {
  ApprovalRequest,
  ApprovalResponse,
  AsyncChatRequest,
  AsyncChatResponse,
  ExportOptions,
  ExportResult,
  ExportWarning,
  JobStatus,
  JobState,
  ProcessDocumentRequest,
  ProcessDocumentResponse,
  ProposedChange,
  ProposedChangeBatch,
  QuotaInfo,
  UploadUrlRequest,
  UploadUrlResponse,
} from "./types";

export const SUPERDOCS_BASE = "https://api.superdocs.app";

export class ApiError extends Error {
  constructor(
    public status: number,
    public body: string,
    public url: string
  ) {
    super(`SuperDocs API ${status} on ${url}: ${body.slice(0, 300)}`);
  }
}

export interface PollCallbacks {
  onAwaitingApproval?: (job: JobStatus, changes: ProposedChange[]) => void | Promise<void>;
  onProgress?: (job: JobStatus) => void;
}

export interface ClientOptions {
  baseUrl?: string;
  pollIntervalMs?: number;
  maxPollSeconds?: number;
  fetchImpl?: typeof fetch;
  onRequest?: (label: string) => void;
}

export class SuperDocsClient {
  private baseUrl: string;
  private pollIntervalMs: number;
  private maxPollSeconds: number;
  private fetchImpl: typeof fetch;
  private onRequest?: (label: string) => void;

  constructor(
    public apiKey: string,
    opts: ClientOptions = {}
  ) {
    this.baseUrl = opts.baseUrl ?? SUPERDOCS_BASE;
    this.pollIntervalMs = opts.pollIntervalMs ?? 2000;
    this.maxPollSeconds = opts.maxPollSeconds ?? 1800;
    this.fetchImpl = opts.fetchImpl ?? fetch;
    this.onRequest = opts.onRequest;
  }

  private headers(json = true): Record<string, string> {
    const h: Record<string, string> = {
      Authorization: `Bearer ${this.apiKey}`,
    };
    if (json) h["Content-Type"] = "application/json";
    return h;
  }

  private async request<T>(
    method: string,
    path: string,
    body?: unknown,
    raw = false
  ): Promise<{ status: number; headers: Headers; body: T }> {
    this.onRequest?.(`${method} ${path}`);
    const init: RequestInit = {
      method,
      headers: this.headers(body !== undefined || raw),
    };
    if (body !== undefined) {
      init.body = typeof body === "string" ? body : JSON.stringify(body);
    }
    const resp = await this.fetchImpl(`${this.baseUrl}${path}`, init);
    const text = await resp.text();
    if (!resp.ok) {
      throw new ApiError(resp.status, text, path);
    }
    let parsed: T;
    if (raw) {
      parsed = text as unknown as T;
    } else if (!text) {
      parsed = {} as T;
    } else {
      try {
        parsed = JSON.parse(text) as T;
      } catch {
        parsed = text as unknown as T;
      }
    }
    return { status: resp.status, headers: resp.headers, body: parsed };
  }

  async whoami(): Promise<QuotaInfo> {
    const { body } = await this.request<QuotaInfo>("GET", "/v1/agents/whoami");
    return body;
  }

  async signup(agentName: string): Promise<{ api_key: string; quota: QuotaInfo }> {
    const { body } = await this.request<{ api_key: string; quota: QuotaInfo }>(
      "POST",
      "/v1/agents/signup",
      { terms_accepted: true, agent_name: agentName }
    );
    return body;
  }

  async requestUploadUrl(req: UploadUrlRequest): Promise<UploadUrlResponse> {
    const { body } = await this.request<UploadUrlResponse>("POST", "/v1/uploads", req);
    return body;
  }

  async putBytes(url: string, bytes: Uint8Array, contentType: string): Promise<void> {
    this.onRequest?.("PUT pre-signed upload");
    const resp = await this.fetchImpl(url, {
      method: "PUT",
      headers: { "Content-Type": contentType },
      body: bytes as unknown as BodyInit,
    });
    if (!resp.ok) {
      throw new ApiError(resp.status, await resp.text(), url);
    }
  }

  async processUpload(
    uploadId: string,
    req: ProcessDocumentRequest
  ): Promise<ProcessDocumentResponse> {
    const { body } = await this.request<ProcessDocumentResponse>(
      "POST",
      `/v1/uploads/${uploadId}/process`,
      req
    );
    return body;
  }

  async chatAsync(req: AsyncChatRequest): Promise<AsyncChatResponse> {
    const { body } = await this.request<AsyncChatResponse>("POST", "/v1/chat/async", req);
    return body;
  }

  async getJob(jobId: string): Promise<JobStatus> {
    const { body } = await this.request<JobStatus>("GET", `/v1/jobs/${jobId}`);
    return body;
  }

  async approve(sessionId: string, req: ApprovalRequest): Promise<ApprovalResponse> {
    const { body } = await this.request<ApprovalResponse>(
      "POST",
      `/v1/chat/${encodeURIComponent(sessionId)}/approve`,
      req
    );
    return body;
  }

  /**
   * Poll a job until terminal state. When the job enters awaiting_approval,
   * the callback fires immediately and the poller keeps watching for the
   * next pause. Approvals must be sent fast: the AI auto-denies stale
   * proposals and self-iterates.
   */
  async poll(
    jobId: string,
    cb: PollCallbacks = {}
  ): Promise<JobStatus> {
    const deadline = Date.now() + this.maxPollSeconds * 1000;
    let lastState: JobState | null = null;
    for (;;) {
      if (Date.now() > deadline) {
        throw new Error(`job ${jobId} did not reach terminal state within ${this.maxPollSeconds}s`);
      }
      const job = await this.getJob(jobId);
      if (job.status !== lastState) {
        lastState = job.status;
        cb.onProgress?.(job);
      }
      const pending = (job.metadata?.pending_changes ?? null) ?? [];
      if (job.status === "awaiting_approval") {
        await cb.onAwaitingApproval?.(job, pending);
      }
      if (job.status === "completed") return job;
      if (job.status === "failed") {
        throw new Error(`job ${jobId} failed: ${job.error ?? "unknown error"}`);
      }
      if (job.status === "cancelled") {
        throw new Error(`job ${jobId} was cancelled`);
      }
      await sleep(this.pollIntervalMs);
    }
  }

  async exportDocx(
    sessionId: string,
    options?: ExportOptions
  ): Promise<ExportResult> {
    this.onRequest?.("POST /v1/documents/export");
    const resp = await this.fetchImpl(`${this.baseUrl}/v1/documents/export`, {
      method: "POST",
      headers: this.headers(true),
      body: JSON.stringify({ session_id: sessionId, format: "docx", options }),
    });
    if (!resp.ok) {
      throw new ApiError(resp.status, await resp.text(), "/v1/documents/export");
    }
    const warnings = parseExportWarnings(resp.headers.get("X-Export-Warnings"));
    const contentType = resp.headers.get("Content-Type") ?? undefined;
    if (contentType?.includes("json")) {
      const parsed = (await resp.json()) as { download_url?: string };
      if (parsed.download_url) {
        const dl = await this.fetchImpl(parsed.download_url);
        if (!dl.ok) {
          throw new ApiError(dl.status, await dl.text(), parsed.download_url);
        }
        return {
          body: Buffer.from(await dl.arrayBuffer()),
          contentType,
          warnings,
        };
      }
    }
    return {
      body: Buffer.from(await resp.arrayBuffer()),
      contentType,
      filename: parseFilename(resp.headers.get("Content-Disposition")),
      warnings,
    };
  }
}

/** Parse the base64/percent JSON X-Export-Warnings header. */
export function parseExportWarnings(header: string | null): ExportWarning[] {
  if (!header) return [];
  let raw = header;
  if (raw.startsWith("%")) {
    try {
      raw = decodeURIComponent(raw);
    } catch {
      /* keep raw */
    }
  }
  try {
    const parsed = JSON.parse(raw);
    if (Array.isArray(parsed)) return parsed as ExportWarning[];
    if (parsed && Array.isArray(parsed.warnings)) return parsed.warnings as ExportWarning[];
  } catch {
    /* header present but not JSON — treat as opaque warning */
  }
  return [{ code: "UNPARSED", message: raw.slice(0, 500) }];
}

function parseFilename(disposition: string | null): string | undefined {
  if (!disposition) return undefined;
  const m = disposition.match(/filename\*?=(?:UTF-8''|")?([^";]+)/i);
  return m ? m[1].replace(/"/g, "").trim() : undefined;
}

export function sleep(ms: number): Promise<void> {
  return new Promise((r) => setTimeout(r, ms));
}

/** Extract all proposed-change batches from a completed job's intermediate responses. */
export function extractBatches(job: JobStatus): ProposedChangeBatch[] {
  const out: ProposedChangeBatch[] = [];
  for (const ir of job.metadata?.intermediate_responses ?? []) {
    if (ir.type === "proposed_change_batch") {
      try {
        out.push(JSON.parse(ir.content) as ProposedChangeBatch);
      } catch {
        /* skip unparsable */
      }
    }
  }
  return out;
}
