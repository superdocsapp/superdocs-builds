import { CONFIG } from "./config.js";
import type { OpsLedger } from "./budget.js";
import type { Logger } from "./logger.js";
import type {
  AgentHandoffRequest,
  AgentWhoamiResponse,
  AsyncChatResponse,
  ChatRequest,
  ChatResponse,
  ContinueResponse,
  DocumentDetail,
  DownloadUrlRequest,
  DownloadUrlResponse,
  HandoffResponse,
  JobStatus,
  ProcessDocumentResponse,
  ProcessUploadRequest,
  SessionDocumentsResponse,
  UploadUrlRequest,
  UploadUrlResponse,
} from "./types.js";

export class AuthError extends Error {
  constructor(
    message = "API key rejected — the key is invalid or revoked, not a downtime issue",
  ) {
    super(message);
    this.name = "AuthError";
  }
}

export class DocumentInUseError extends Error {
  constructor(
    message: string,
    public readonly openInSessions?: number,
    public readonly suggestedAction?: string,
  ) {
    super(message);
    this.name = "DocumentInUseError";
  }
}

export class TurnRevertedError extends Error {
  constructor(
    message: string,
    public readonly activeTurns?: unknown,
  ) {
    super(message);
    this.name = "TurnRevertedError";
  }
}

export class QuotaError extends Error {
  constructor(
    message: string,
    public readonly retryHint?: string,
  ) {
    super(message);
    this.name = "QuotaError";
  }
}

export class ServerError extends Error {
  constructor(
    message: string,
    public readonly status: number,
  ) {
    super(message);
    this.name = "ServerError";
  }
}

export class NetworkError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "NetworkError";
  }
}

interface RequestOpts {
  query?: Record<string, string | number | boolean>;
  attempt?: number;
}

const MAX_RETRIES = 2;

export class SuperDocsClient {
  constructor(
    private readonly apiKey: string,
    private readonly logger: Logger,
    private readonly ledger: OpsLedger | null,
  ) {}

  private async request<T>(
    method: string,
    path: string,
    body?: unknown,
    opts?: RequestOpts,
  ): Promise<T> {
    const attempt = opts?.attempt ?? 0;
    const qs = opts?.query
      ? `?${new URLSearchParams(
          Object.entries(opts.query).map(([k, v]) => [k, String(v)]),
        ).toString()}`
      : "";
    const url = `${CONFIG.API_BASE}${path}${qs}`;

    const start = Date.now();
    let res: Response;
    try {
      res = await fetch(url, {
        method,
        headers: {
          Authorization: `Bearer ${this.apiKey}`,
          "Content-Type": "application/json",
        },
        body: body === undefined ? undefined : JSON.stringify(body),
      });
    } catch (err) {
      throw new NetworkError(
        `${method} ${path} failed: ${err instanceof Error ? err.message : String(err)}`,
      );
    }

    const durationMs = Date.now() - start;
    this.logger.record({
      type: "http",
      message: `${method} ${path}`,
      data: { status: res.status, durationMs },
    });

    if (res.ok) {
      // Non-fatal export issues surface here rather than in the body —
      // worth surfacing regardless of which endpoint returned it.
      const exportWarnings = res.headers.get("X-Export-Warnings");
      if (exportWarnings) {
        this.logger.warn(`${method} ${path}: export warnings — ${exportWarnings}`);
      }
      return (await res.json()) as T;
    }

    const rawBody: unknown = await res.json().catch(() => ({}));
    const detail =
      typeof rawBody === "object" && rawBody !== null && "detail" in rawBody
        ? (rawBody as { detail: unknown }).detail
        : rawBody;
    const code =
      typeof detail === "object" && detail !== null && "code" in detail
        ? (detail as { code?: unknown }).code
        : undefined;

    if (res.status === 401) {
      throw new AuthError();
    }
    if (res.status === 409 && code === "document_in_use") {
      const d = detail as { open_in_sessions?: number; suggested_action?: string };
      throw new DocumentInUseError(
        `${method} ${path}: document open in ${d.open_in_sessions ?? "another"} session(s)`,
        d.open_in_sessions,
        d.suggested_action,
      );
    }
    if (res.status === 409 && code === "turn_already_reverted") {
      const d = detail as { active_turns?: unknown };
      throw new TurnRevertedError(`${method} ${path}: turn already reverted`, d.active_turns);
    }
    if (res.status === 429) {
      throw new QuotaError(
        `${method} ${path}: rate limited`,
        res.headers.get("Retry-After") ?? undefined,
      );
    }
    if (res.status >= 500) {
      if (attempt < MAX_RETRIES) {
        const delayMs = 500 * 2 ** attempt;
        this.logger.warn(
          `${method} ${path} returned ${res.status} — retrying in ${delayMs}ms (attempt ${attempt + 1}/${MAX_RETRIES})`,
        );
        await new Promise((resolve) => setTimeout(resolve, delayMs));
        return this.request<T>(method, path, body, { ...opts, attempt: attempt + 1 });
      }
      throw new ServerError(`${method} ${path} failed after retries: ${res.status}`, res.status);
    }

    throw new Error(`${method} ${path} failed: ${res.status} ${res.statusText}`);
  }

  // /v1/users/me/usage and /v1/users/me/limits accept web-app session tokens
  // ONLY and reject sk_ agent keys with 401 — do not add methods for them.
  // Read usage from the `usage` block on every chat/job response instead.

  async whoami(): Promise<AgentWhoamiResponse> {
    const result = await this.request<AgentWhoamiResponse>("GET", "/v1/agents/whoami");
    this.ledger?.record("whoami");
    return result;
  }

  async chat(body: ChatRequest): Promise<ChatResponse> {
    const result = await this.request<ChatResponse>("POST", "/v1/chat", body);
    this.ledger?.record("chat", result.usage);
    return result;
  }

  async chatAsync(body: ChatRequest): Promise<AsyncChatResponse> {
    const result = await this.request<AsyncChatResponse>("POST", "/v1/chat/async", {
      ...body,
      async_mode: true,
    });
    // No usage block yet — the job hasn't run. Real billing surfaces later,
    // in result.usage once getJob() reports status 'completed'.
    this.ledger?.record("chatAsync");
    return result;
  }

  async getJob(jobId: string): Promise<JobStatus> {
    const result = await this.request<JobStatus>("GET", `/v1/jobs/${jobId}`);
    this.ledger?.record(
      "getJob",
      result.status === "completed" ? result.result?.usage : undefined,
    );
    return result;
  }

  async continueChat(
    sessionId: string,
    jobId: string,
    shouldContinue: boolean,
  ): Promise<ContinueResponse> {
    const result = await this.request<ContinueResponse>(
      "POST",
      `/v1/chat/${sessionId}/continue`,
      { job_id: jobId, continue: shouldContinue },
    );
    this.ledger?.record("continueChat");
    return result;
  }

  async cancelJob(jobId: string): Promise<JobStatus> {
    const result = await this.request<JobStatus>("POST", `/v1/jobs/${jobId}/cancel`);
    this.ledger?.record("cancelJob");
    return result;
  }

  async getDocument(id: string, includeHtml = false): Promise<DocumentDetail> {
    const result = await this.request<DocumentDetail>("GET", `/v1/documents/${id}`, undefined, {
      query: { include_html: includeHtml },
    });
    // structure is derived on read and never billed — always a free read.
    this.ledger?.record("getDocument");
    return result;
  }

  async listSessionDocuments(sessionId: string): Promise<SessionDocumentsResponse> {
    const result = await this.request<SessionDocumentsResponse>(
      "GET",
      `/v1/sessions/${sessionId}/documents`,
    );
    this.ledger?.record("listSessionDocuments");
    return result;
  }

  async requestDownloadUrl(body: DownloadUrlRequest): Promise<DownloadUrlResponse> {
    const result = await this.request<DownloadUrlResponse>("POST", "/v1/downloads", body);
    this.ledger?.record("requestDownloadUrl");
    return result;
  }

  async requestUploadUrl(body: UploadUrlRequest): Promise<UploadUrlResponse> {
    const result = await this.request<UploadUrlResponse>("POST", "/v1/uploads", body);
    this.ledger?.record("requestUploadUrl");
    return result;
  }

  async processUpload(
    uploadId: string,
    body: ProcessUploadRequest,
  ): Promise<ProcessDocumentResponse> {
    const result = await this.request<ProcessDocumentResponse>(
      "POST",
      `/v1/uploads/${uploadId}/process`,
      body,
    );
    this.ledger?.record("processUpload");
    return result;
  }

  async handoff(body: AgentHandoffRequest): Promise<HandoffResponse> {
    const result = await this.request<HandoffResponse>("POST", "/v1/agents/handoff", body);
    this.ledger?.record("handoff");
    return result;
  }
}
