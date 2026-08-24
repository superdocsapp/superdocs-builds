import { requestUrl } from "obsidian";
import type { JobStatus, JobUsage, PendingChange } from "./types";

interface RequestOptions {
  method?: "GET" | "POST";
  body?: unknown;
  binary?: boolean;
}

export interface UploadedDocument {
  html?: string;
  chunks_count?: number;
  [key: string]: unknown;
}

interface AttachmentStatus {
  processing_jobs?: Array<{ filename?: string; status?: string; error?: string | null }>;
  ready_attachments?: Array<{ filename?: string }>;
  total_processing?: number;
}

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => window.setTimeout(resolve, ms));
}

export class SuperDocsError extends Error {
  readonly status: number;
  readonly code?: string;

  constructor(message: string, status: number, code?: string) {
    super(message);
    this.name = "SuperDocsError";
    this.status = status;
    this.code = code;
  }
}

export class SuperDocsClient {
  private readonly baseUrl: string;
  private readonly headers: Record<string, string>;

  constructor(baseUrl: string, apiKey: string) {
    this.baseUrl = baseUrl.replace(/\/+$/, "");
    this.headers = {
      Authorization: `Bearer ${apiKey}`,
      "Content-Type": "application/json",
    };
  }

  private async request<T>(path: string, options: RequestOptions = {}): Promise<T> {
    const response = await requestUrl({
      url: `${this.baseUrl}${path}`,
      method: options.method ?? "GET",
      headers: this.headers,
      body: options.body === undefined ? undefined : JSON.stringify(options.body),
      throw: false,
    });
    if (response.status < 200 || response.status >= 300) {
      let detail = "request failed";
      try {
        const parsed = JSON.parse(response.text) as { detail?: unknown; error?: unknown };
        detail = typeof parsed.detail === "string" ? parsed.detail : typeof parsed.error === "string" ? parsed.error : detail;
      } catch {
        // The body can be an HTML gateway error; do not echo it into a notice.
      }
      throw new SuperDocsError(`${detail} (HTTP ${response.status})`, response.status);
    }
    if (options.binary) return response.arrayBuffer as T;
    try {
      return response.json as T;
    } catch {
      return JSON.parse(response.text) as T;
    }
  }

  /** The editable document. Only owned-region content is ever sent here. */
  async uploadDocument(sessionId: string, filename: string, markdown: string): Promise<UploadedDocument> {
    return this.request<UploadedDocument>("/v1/documents/upload-base64", {
      method: "POST",
      body: {
        filename,
        file_base64: encodeBase64(markdown),
        session_id: sessionId,
        return_html: true,
      },
    });
  }

  /** Read-only context. Attachments cannot be edited by the agent. */
  async uploadReference(sessionId: string, filename: string, markdown: string): Promise<void> {
    await this.request<Record<string, unknown>>("/v1/attachments/upload-base64", {
      method: "POST",
      body: {
        filename,
        file_base64: encodeBase64(markdown),
        session_id: sessionId,
      },
    });
  }

  async waitForAttachments(sessionId: string, expected: number, timeoutMs = 120_000): Promise<void> {
    if (expected === 0) return;
    const deadline = Date.now() + timeoutMs;
    while (Date.now() < deadline) {
      const status = await this.request<AttachmentStatus>(`/v1/attachments/status/${encodeURIComponent(sessionId)}`);
      const failed = (status.processing_jobs ?? []).find((job) => job.status === "failed");
      if (failed) {
        throw new SuperDocsError(`reference attachment '${failed.filename ?? "unknown"}' failed to process; no edit was started`, 422, "attachment_failed");
      }
      const pending = (status.processing_jobs ?? []).filter((job) => job.status !== "completed").length;
      const ready = (status.ready_attachments ?? []).length;
      if (pending === 0 && ready >= expected) return;
      await sleep(1_500);
    }
    throw new SuperDocsError("reference attachments did not finish processing in time; no edit was started", 408, "attachment_timeout");
  }

  async startReconciliation(args: {
    sessionId: string;
    message: string;
    modelTier: string;
    thinkingDepth: string;
    crossSessionSearch: boolean;
    crossSessionMemory: boolean;
    memoryKey?: string;
  }): Promise<string> {
    const result = await this.request<{ job_id?: string }>("/v1/chat/async", {
      method: "POST",
      body: {
        message: args.message,
        session_id: args.sessionId,
        async_mode: true,
        approval_mode: "ask_every_time",
        response_mode: "full",
        model_tier: args.modelTier,
        thinking_depth: args.thinkingDepth,
        cross_session_search: args.crossSessionSearch,
        cross_session_memory: args.crossSessionMemory,
        ...(args.memoryKey ? { cross_session_memory_key: args.memoryKey } : {}),
      },
    });
    if (!result.job_id) throw new SuperDocsError("SuperDocs did not return a job id", 502, "missing_job_id");
    return result.job_id;
  }

  async getJob(jobId: string): Promise<JobStatus> {
    return this.request<JobStatus>(`/v1/jobs/${encodeURIComponent(jobId)}`);
  }

  /**
   * The API requires a top-level `approved` even when every entry carries its
   * own decision; without it the request is rejected with a bare 422.
   */
  async approveChanges(sessionId: string, jobId: string, decisions: Array<{ change_id: string; approved: boolean; feedback?: string }>): Promise<void> {
    if (decisions.length === 0) return;
    await this.request(`/v1/chat/${encodeURIComponent(sessionId)}/approve`, {
      method: "POST",
      body: {
        job_id: jobId,
        approved: decisions.some((decision) => decision.approved),
        changes: decisions,
      },
    });
  }

  async exportMarkdown(sessionId: string): Promise<string> {
    const bytes = await this.request<ArrayBuffer>("/v1/documents/export", {
      method: "POST",
      body: { session_id: sessionId, format: "markdown", options: { filename: "living-note" } },
      binary: true,
    });
    return new TextDecoder().decode(bytes);
  }
}

function encodeBase64(value: string): string {
  const bytes = new TextEncoder().encode(value);
  let binary = "";
  const chunkSize = 0x8000;
  for (let i = 0; i < bytes.length; i += chunkSize) {
    binary += String.fromCharCode(...bytes.subarray(i, i + chunkSize));
  }
  return btoa(binary);
}

/**
 * Polling returns proposed changes as objects. The SSE surface delivers the same
 * payload as a JSON string, so a string entry is parsed rather than dropped.
 */
export function pendingChanges(job: JobStatus): PendingChange[] {
  const raw = job.metadata?.pending_changes;
  if (!Array.isArray(raw)) return [];
  const changes: PendingChange[] = [];
  for (const entry of raw) {
    if (typeof entry === "string") {
      try {
        changes.push(JSON.parse(entry) as PendingChange);
      } catch {
        throw new SuperDocsError("SuperDocs returned a proposed change that could not be read", 502, "unreadable_change");
      }
      continue;
    }
    if (entry && typeof entry === "object") changes.push(entry as PendingChange);
  }
  return changes;
}

export function jobUsage(job: JobStatus): JobUsage {
  return job.usage ?? job.result?.usage ?? {};
}
