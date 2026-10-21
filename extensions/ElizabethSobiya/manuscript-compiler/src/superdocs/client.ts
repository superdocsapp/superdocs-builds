/**
 * SuperDocs REST client.
 *
 * Covers the four calls the integration contract asks for — upload, chat, approve,
 * export — plus image upload and templates, which a manuscript genuinely needs.
 *
 * Transport is injected rather than imported, for two reasons: Obsidian wants its
 * own `requestUrl` (CORS-free, desktop and mobile), Node wants `fetch`, and the
 * test suite wants neither. Every behaviour claimed in the README is therefore
 * testable without a key and without spending an operation.
 */

export interface HttpRequest {
  method: "GET" | "POST" | "PUT" | "DELETE";
  url: string;
  headers: Record<string, string>;
  /** JSON body, or a multipart body already encoded. */
  body?: string | ArrayBuffer;
}

export interface HttpResponse {
  status: number;
  headers: Record<string, string>;
  text: string;
  arrayBuffer: ArrayBuffer;
}

export type Transport = (req: HttpRequest) => Promise<HttpResponse>;

export const DEFAULT_API_BASE = "https://api.superdocs.app";

export class SuperDocsError extends Error {
  constructor(
    message: string,
    readonly status: number,
    readonly code: string,
    readonly body: string,
  ) {
    super(message);
    this.name = "SuperDocsError";
  }

  /** 429 and 5xx are worth retrying; 4xx below that means the request is wrong. */
  get retryable(): boolean {
    return this.status === 429 || this.status >= 500;
  }
}

export interface Usage {
  monthly_used?: number;
  monthly_limit?: number;
  monthly_remaining?: number;
  was_billable?: boolean;
  ops_charged?: number;
  subscription_tier?: string;
}

export interface ProposedChange {
  change_id: string;
  operation: "edit" | "create" | "delete";
  chunk_id: string | null;
  old_html: string | null;
  new_html: string | null;
  ai_explanation: string;
  insert_after_chunk_id?: string | null;
  insert_before_chunk_id?: string | null;
  status?: string;
}

export interface ChatResult {
  session_id?: string;
  response?: string;
  document_changes?: {
    updated_html?: string;
    changes?: ProposedChange[];
    pending_changes?: ProposedChange[] | null;
    requires_approval?: boolean | null;
    changes_summary?: string;
  } | null;
  usage?: Usage;
  hint?: string | null;
}

export interface JobStatus {
  job_id: string;
  // The API uses both "processing" and "in_progress" for the same running state.
  status:
    | "queued"
    | "processing"
    | "in_progress"
    | "awaiting_approval"
    | "completed"
    | "failed"
    | "cancelled";
  metadata?: {
    awaiting_kind?: string;
    pending_changes?: ProposedChange[];
  } | null;
  result?: ChatResult | null;
  error?: string | null;
  usage?: Usage;
}

export interface ExportOptions {
  paper_size?: "Letter" | "A4" | "A3" | "Legal";
  orientation?: "portrait" | "landscape";
  margins?: "narrow" | "normal" | "wide" | "custom";
  custom_margins_inches?: { top: number; right: number; bottom: number; left: number };
  filename?: string;
  watermark_text?: string;
  watermark_opacity?: number;
  embed_images?: boolean;
}

export interface ExportWarning {
  code: string;
  message: string;
  detail?: unknown;
}

export interface ExportResult {
  bytes: ArrayBuffer;
  warnings: ExportWarning[];
  contentType: string;
}

export interface ClientOptions {
  apiKey: string;
  transport: Transport;
  apiBase?: string;
  /** Called before every request, so callers can show progress or count spend. */
  onRequest?: (info: { method: string; path: string }) => void;
  onUsage?: (usage: Usage) => void;
  /** Injected so tests can run retry logic without real delays. */
  sleep?: (ms: number) => Promise<void>;
  maxRetries?: number;
}

/** Inline export bodies above this are rejected by the gateway; use pre-signed upload. */
export const INLINE_EXPORT_LIMIT_BYTES = 20 * 1024 * 1024;

export class SuperDocsClient {
  private readonly base: string;
  private readonly maxRetries: number;
  private readonly sleep: (ms: number) => Promise<void>;

  constructor(private readonly opts: ClientOptions) {
    this.base = (opts.apiBase ?? DEFAULT_API_BASE).replace(/\/+$/, "");
    this.maxRetries = opts.maxRetries ?? 3;
    this.sleep = opts.sleep ?? ((ms) => new Promise((r) => setTimeout(r, ms)));
  }

  // --- plumbing -------------------------------------------------------------

  private authHeaders(extra: Record<string, string> = {}): Record<string, string> {
    return { Authorization: `Bearer ${this.opts.apiKey}`, ...extra };
  }

  private async request(req: HttpRequest, attempt = 0): Promise<HttpResponse> {
    this.opts.onRequest?.({ method: req.method, path: req.url.slice(this.base.length) });
    const res = await this.opts.transport(req);
    if (res.status >= 200 && res.status < 300) return res;

    const err = toError(res);
    if (err.retryable && attempt < this.maxRetries) {
      // Exponential backoff with a floor, honouring Retry-After when present.
      const retryAfter = Number(res.headers["retry-after"] ?? res.headers["Retry-After"] ?? 0);
      const delay = retryAfter > 0 ? retryAfter * 1000 : Math.min(2 ** attempt * 1000, 8000);
      await this.sleep(delay);
      return this.request(req, attempt + 1);
    }
    throw err;
  }

  private async postJson<T>(path: string, body: unknown): Promise<T> {
    const res = await this.request({
      method: "POST",
      url: `${this.base}${path}`,
      headers: this.authHeaders({ "Content-Type": "application/json" }),
      body: JSON.stringify(body),
    });
    return parseJson<T>(res.text, path);
  }

  private async getJson<T>(path: string): Promise<T> {
    const res = await this.request({
      method: "GET",
      url: `${this.base}${path}`,
      headers: this.authHeaders(),
    });
    return parseJson<T>(res.text, path);
  }

  private noteUsage(usage: Usage | undefined): void {
    if (usage) this.opts.onUsage?.(usage);
  }

  // --- 0. credentials -------------------------------------------------------

  /** Cheapest way to confirm a key works. `/v1/users/me` rejects API keys — do not use it. */
  async verifyKey(): Promise<boolean> {
    try {
      await this.getJson<unknown>("/v1/sessions");
      return true;
    } catch (err) {
      if (err instanceof SuperDocsError && err.status === 401) return false;
      throw err;
    }
  }

  async accountStatus(): Promise<{ quota?: { remaining?: number; monthly_limit?: number } }> {
    return this.getJson("/v1/agents/whoami");
  }

  // --- 1. upload ------------------------------------------------------------

  /** Upload the compiled manuscript as the session's active editable document. */
  async uploadDocument(args: {
    sessionId: string;
    filename: string;
    content: string;
    contentType?: string;
  }): Promise<{ session_id?: string; document_html?: string }> {
    const multipart = buildMultipart([
      { name: "session_id", value: args.sessionId },
      {
        name: "file",
        filename: args.filename,
        contentType: args.contentType ?? "text/html",
        value: args.content,
      },
    ]);
    const res = await this.request({
      method: "POST",
      url: `${this.base}/v1/documents/upload`,
      headers: this.authHeaders({ "Content-Type": multipart.contentType }),
      body: multipart.body,
    });
    return parseJson(res.text, "/v1/documents/upload");
  }

  // --- 2. chat --------------------------------------------------------------

  /** Synchronous edit. Right for small, fast instructions. */
  async chat(args: {
    sessionId: string;
    message: string;
    documentHtml?: string;
    approvalMode?: "approve_all" | "ask_every_time";
    modelTier?: "core" | "pro" | "max";
    thinkingDepth?: "fast" | "balanced" | "deep";
  }): Promise<ChatResult> {
    const result = await this.postJson<ChatResult>("/v1/chat", {
      message: args.message,
      session_id: args.sessionId,
      ...(args.documentHtml !== undefined ? { document_html: args.documentHtml } : {}),
      approval_mode: args.approvalMode ?? "approve_all",
      ...(args.modelTier ? { model_tier: args.modelTier } : {}),
      ...(args.thinkingDepth ? { thinking_depth: args.thinkingDepth } : {}),
    });
    this.noteUsage(result.usage);
    return result;
  }

  /** Asynchronous edit. Required for review mode, and for anything book-sized. */
  async chatAsync(args: {
    sessionId: string;
    message: string;
    documentHtml?: string;
    approvalMode?: "approve_all" | "ask_every_time";
    modelTier?: "core" | "pro" | "max";
  }): Promise<{ job_id: string }> {
    return this.postJson("/v1/chat/async", {
      message: args.message,
      session_id: args.sessionId,
      ...(args.documentHtml !== undefined ? { document_html: args.documentHtml } : {}),
      approval_mode: args.approvalMode ?? "ask_every_time",
      ...(args.modelTier ? { model_tier: args.modelTier } : {}),
    });
  }

  async getJob(jobId: string): Promise<JobStatus> {
    const job = await this.getJson<JobStatus>(`/v1/jobs/${encodeURIComponent(jobId)}`);
    // An async job reports its spend on the job, on its result, or on neither
    // depending on where it is in its life; check both so the spend counter is honest.
    this.noteUsage(job.usage ?? job.result?.usage);
    return job;
  }

  async cancelJob(jobId: string): Promise<void> {
    await this.postJson(`/v1/jobs/${encodeURIComponent(jobId)}/cancel`, {});
  }

  // --- 3. approve -----------------------------------------------------------

  /**
   * Approve or reject proposed changes, item by item.
   *
   * The top-level `approved` field is required by the API even when every entry in
   * `changes` carries its own decision; omitting it returns a bare 422 that says
   * nothing useful. It is always sent here.
   */
  async approve(args: {
    sessionId: string;
    jobId: string;
    decisions: Array<{ changeId: string; approved: boolean; feedback?: string }>;
  }): Promise<unknown> {
    if (args.decisions.length === 0) return {};
    if (args.decisions.length === 1) {
      const d = args.decisions[0]!;
      return this.postJson(`/v1/chat/${encodeURIComponent(args.sessionId)}/approve`, {
        job_id: args.jobId,
        change_id: d.changeId,
        approved: d.approved,
        ...(d.feedback ? { feedback: d.feedback } : {}),
      });
    }
    return this.postJson(`/v1/chat/${encodeURIComponent(args.sessionId)}/approve`, {
      job_id: args.jobId,
      approved: true, // required by the schema; per-change values below win
      changes: args.decisions.map((d) => ({
        change_id: d.changeId,
        approved: d.approved,
        ...(d.feedback ? { feedback: d.feedback } : {}),
      })),
    });
  }

  // --- 4. export ------------------------------------------------------------

  async exportDocument(args: {
    format: "docx" | "pdf" | "html" | "markdown" | "txt";
    html?: string;
    sessionId?: string;
    options?: ExportOptions;
  }): Promise<ExportResult> {
    const body: Record<string, unknown> = { format: args.format };
    if (args.html !== undefined) {
      const bytes = utf8Length(args.html);
      if (bytes > INLINE_EXPORT_LIMIT_BYTES) {
        const uploadId = await this.uploadForExport(args.html);
        body.upload_id = uploadId;
        body.filename = `${args.options?.filename ?? "manuscript"}.html`;
      } else {
        body.html = args.html;
      }
    } else if (args.sessionId) {
      body.session_id = args.sessionId;
    } else {
      throw new Error("exportDocument needs either html or sessionId");
    }
    if (args.options) body.options = args.options;

    const res = await this.request({
      method: "POST",
      url: `${this.base}/v1/documents/export`,
      headers: this.authHeaders({ "Content-Type": "application/json" }),
      body: JSON.stringify(body),
    });
    return {
      bytes: res.arrayBuffer,
      warnings: decodeExportWarnings(res.headers),
      contentType: res.headers["content-type"] ?? "application/octet-stream",
    };
  }

  /** Pre-signed upload path for manuscripts over the inline body limit. */
  private async uploadForExport(html: string): Promise<string> {
    const upload = await this.postJson<{ upload_id: string; upload_url: string }>("/v1/uploads", {
      filename: "manuscript.html",
      content_type: "text/html",
      size_bytes: utf8Length(html),
      purpose: "export-html",
    });
    // Straight to storage, not through the API: no auth header, and a real PUT.
    const put = await this.opts.transport({
      method: "PUT",
      url: upload.upload_url,
      headers: { "Content-Type": "text/html" },
      body: html,
    });
    if (put.status < 200 || put.status >= 300) {
      throw new SuperDocsError(
        `Pre-signed upload failed with ${put.status}. The signed URL is valid for five minutes; retry the export.`,
        put.status,
        "presigned_upload_failed",
        put.text.slice(0, 500),
      );
    }
    return upload.upload_id;
  }

  // --- images and templates -------------------------------------------------

  /**
   * Upload one figure and get back a stable URL.
   *
   * This is not optional polish: data: URIs in `<img src>` are dropped from the
   * export with no warning, so a figure that is not uploaded simply does not
   * appear in the PDF or the .docx. Verified against the live exporter.
   */
  async uploadImage(args: {
    base64: string;
    filename: string;
  }): Promise<{ url: string }> {
    return this.postJson("/v1/documents/images/upload-base64", {
      image_base64: args.base64,
      filename: args.filename,
    });
  }

  async uploadTemplate(args: {
    filename: string;
    content: ArrayBuffer;
    contentType: string;
  }): Promise<unknown> {
    const multipart = buildMultipart([
      {
        name: "file",
        filename: args.filename,
        contentType: args.contentType,
        value: args.content,
      },
    ]);
    const res = await this.request({
      method: "POST",
      url: `${this.base}/v1/templates/upload`,
      headers: this.authHeaders({ "Content-Type": multipart.contentType }),
      body: multipart.body,
    });
    return parseJson(res.text, "/v1/templates/upload");
  }

  async listTemplates(): Promise<unknown> {
    return this.getJson("/v1/templates");
  }
}

// --- helpers ----------------------------------------------------------------

function toError(res: HttpResponse): SuperDocsError {
  let code = `http_${res.status}`;
  let message = `SuperDocs returned ${res.status}`;
  try {
    const parsed = JSON.parse(res.text) as { detail?: unknown; error?: unknown };
    const detail = parsed.detail ?? parsed.error;
    if (typeof detail === "string") message = detail;
    else if (detail && typeof detail === "object") {
      const d = detail as { message?: string; code?: string };
      if (d.message) message = d.message;
      if (d.code) code = d.code;
    }
  } catch {
    if (res.text) message = `${message}: ${res.text.slice(0, 200)}`;
  }
  if (res.status === 401) {
    message =
      "SuperDocs rejected the API key (401). Check the key in settings — note that /v1/users/me returns 401 for valid API keys, so verify with /v1/sessions instead.";
  }
  return new SuperDocsError(message, res.status, code, res.text.slice(0, 2000));
}

function parseJson<T>(text: string, path: string): T {
  if (!text.trim()) return {} as T;
  try {
    return JSON.parse(text) as T;
  } catch {
    throw new SuperDocsError(
      `SuperDocs returned a non-JSON body from ${path}. This usually means a gateway error page rather than an API response.`,
      0,
      "invalid_json",
      text.slice(0, 500),
    );
  }
}

/**
 * `proposed_change_batch` content arrives JSON-encoded inside a JSON field, so a
 * naive parse leaves every field `undefined`. Anything that reads changes off the
 * wire goes through here.
 */
export function parseMaybeEncoded<T>(value: unknown): T | null {
  if (value === null || value === undefined) return null;
  if (typeof value === "object") return value as T;
  if (typeof value === "string") {
    const trimmed = value.trim();
    if (!trimmed) return null;
    try {
      const once = JSON.parse(trimmed) as unknown;
      return typeof once === "string" ? (JSON.parse(once) as T) : (once as T);
    } catch {
      return null;
    }
  }
  return null;
}

export function decodeExportWarnings(headers: Record<string, string>): ExportWarning[] {
  const raw = headers["x-export-warnings"] ?? headers["X-Export-Warnings"];
  if (!raw) return [];
  try {
    const json =
      typeof atob === "function"
        ? atob(raw)
        : Buffer.from(raw, "base64").toString("utf-8");
    const parsed = JSON.parse(json) as unknown;
    return Array.isArray(parsed) ? (parsed as ExportWarning[]) : [];
  } catch {
    return [];
  }
}

function utf8Length(s: string): number {
  return typeof TextEncoder !== "undefined" ? new TextEncoder().encode(s).length : s.length;
}

interface MultipartField {
  name: string;
  value: string | ArrayBuffer;
  filename?: string;
  contentType?: string;
}

/**
 * Hand-rolled multipart, because Obsidian's `requestUrl` takes an ArrayBuffer body
 * rather than a FormData object, and FormData is not available identically across
 * desktop, mobile and Node.
 */
export function buildMultipart(fields: MultipartField[]): {
  body: ArrayBuffer;
  contentType: string;
} {
  const boundary = `----ManuscriptCompiler${Math.random().toString(36).slice(2)}${Date.now().toString(36)}`;
  const chunks: Uint8Array[] = [];
  const enc = new TextEncoder();

  for (const field of fields) {
    let header = `--${boundary}\r\nContent-Disposition: form-data; name="${field.name}"`;
    if (field.filename) header += `; filename="${field.filename}"`;
    header += "\r\n";
    if (field.contentType) header += `Content-Type: ${field.contentType}\r\n`;
    header += "\r\n";
    chunks.push(enc.encode(header));
    chunks.push(
      typeof field.value === "string" ? enc.encode(field.value) : new Uint8Array(field.value),
    );
    chunks.push(enc.encode("\r\n"));
  }
  chunks.push(enc.encode(`--${boundary}--\r\n`));

  const total = chunks.reduce((n, c) => n + c.length, 0);
  const out = new Uint8Array(total);
  let offset = 0;
  for (const c of chunks) {
    out.set(c, offset);
    offset += c.length;
  }
  return { body: out.buffer, contentType: `multipart/form-data; boundary=${boundary}` };
}
