import "dotenv/config";
import { appendUsageRecord, type SuperDocsUsage, usageFromApi } from "./telemetry.js";

export interface SuperDocsConfig {
  apiKey: string;
  baseUrl: string;
  usagePath?: string;
}

export interface SuperDocsChatResponse {
  sessionId?: string;
  jobId?: string;
  documentChanges?: unknown;
  usage?: SuperDocsUsage;
  raw: unknown;
}

export interface SuperDocsAsyncResponse {
  sessionId?: string;
  jobId: string;
  usage?: SuperDocsUsage;
  raw: unknown;
}

export interface SuperDocsJobResponse {
  jobId: string;
  status?: string;
  documentChanges?: unknown;
  usage?: SuperDocsUsage;
  raw: unknown;
}

export interface SuperDocsApproval {
  jobId: string;
  approved: boolean;
  changes?: Array<{
    changeId: string;
    approved: boolean;
    feedback?: string;
  }>;
}

export interface SuperDocsExportInput {
  html?: string;
  sessionId?: string;
  format: "doc" | "docx";
  filename?: string;
}

export class SuperDocsClient {
  private readonly recordedUsageKeys = new Set<string>();

  constructor(private readonly config: SuperDocsConfig) {
    if (!config.apiKey) {
      throw new Error("SUPERDOCS_API_KEY is required.");
    }
  }

  static fromEnv(): SuperDocsClient {
    const apiKey = process.env.SUPERDOCS_API_KEY ?? "";
    const baseUrl = process.env.SUPERDOCS_BASE_URL ?? "https://api.superdocs.app";
    return new SuperDocsClient({
      apiKey,
      baseUrl,
      usagePath: process.env.SUPERDOCS_USAGE_PATH ?? "superdocs-usage.json",
    });
  }

  async chat(payload: Record<string, unknown>): Promise<SuperDocsChatResponse> {
    const documentHtml = payload.document_html;
    if (typeof documentHtml !== "string" || documentHtml.trim().length === 0) {
      throw new Error("SuperDocs chat requires a non-empty document_html value.");
    }
    if (typeof payload.session_id !== "string" || payload.session_id.trim().length === 0) {
      throw new Error("SuperDocs chat requires a non-empty session_id value.");
    }

    const raw = await this.requestJson("/v1/chat", payload);

    const object = isRecord(raw) ? raw : {};
    const usage = usageFromApi(object["usage"]);
    await this.persistUsage(usage, "chat", stringOrUndefined(object["session_id"]));
    return {
      sessionId: stringOrUndefined(object["session_id"]),
      jobId: stringOrUndefined(object["job_id"]),
      documentChanges: parseNestedJson(object["document_changes"]),
      usage,
      raw,
    };
  }

  async chatAsync(payload: Record<string, unknown>): Promise<SuperDocsAsyncResponse> {
    const documentHtml = payload.document_html;
    if (typeof documentHtml !== "string" || documentHtml.trim().length === 0) {
      throw new Error("SuperDocs async chat requires a non-empty document_html value.");
    }
    if (typeof payload.session_id !== "string" || payload.session_id.trim().length === 0) {
      throw new Error("SuperDocs async chat requires a non-empty session_id value.");
    }

    const raw = await this.requestJson("/v1/chat/async", payload);
    const object = isRecord(raw) ? raw : {};
    const jobId = stringOrUndefined(object["job_id"]);
    if (!jobId) throw new Error("SuperDocs async chat did not return a job_id.");
    const usage = usageFromApi(object["usage"]);
    await this.persistUsage(usage, "async-chat", String(payload.session_id), jobId);
    return {
      sessionId: stringOrUndefined(object["session_id"]) ?? String(payload.session_id),
      jobId,
      usage,
      raw,
    };
  }

  async getJob(jobId: string): Promise<SuperDocsJobResponse> {
    if (!jobId) throw new Error("SuperDocs job lookup requires a jobId.");
    const response = await this.request(`/v1/jobs/${encodeURIComponent(jobId)}`, { method: "GET" });
    const raw = await parseJsonResponse(response);
    const object = isRecord(raw) ? raw : {};
    const result = isRecord(object["result"]) ? object["result"] : undefined;
    const usage = usageFromApi(result?.["usage"] ?? object["usage"]);
    const sessionId = stringOrUndefined(object["session_id"])
      ?? (result && stringOrUndefined(result["session_id"]));
    if (usage && ["completed", "complete", "succeeded"].includes(stringOrUndefined(object["status"])?.toLowerCase() ?? "")) {
      await this.persistUsage(usage, "job", sessionId, jobId);
    }
    return {
      jobId,
      status: stringOrUndefined(object["status"]),
      documentChanges: parseNestedJson(object["document_changes"]),
      usage,
      raw,
    };
  }

  async waitForJob(
    jobId: string,
    options: { pollIntervalMs?: number; maxWaitMs?: number } = {},
  ): Promise<SuperDocsJobResponse> {
    const pollIntervalMs = options.pollIntervalMs ?? 2000;
    const maxWaitMs = options.maxWaitMs ?? 120000;
    const startedAt = Date.now();

    while (true) {
      const result = await this.getJob(jobId);
      const status = result.status?.toLowerCase();
      if (status && ["completed", "complete", "succeeded", "awaiting_approval", "failed", "error", "cancelled"].includes(status)) {
        return result;
      }
      if (Date.now() - startedAt >= maxWaitMs) {
        throw new Error(`SuperDocs job ${jobId} did not finish within ${maxWaitMs}ms.`);
      }
      await new Promise((resolve) => setTimeout(resolve, pollIntervalMs));
    }
  }

  async approve(sessionId: string, approval: SuperDocsApproval): Promise<unknown> {
    if (!sessionId) throw new Error("SuperDocs approval requires a sessionId.");
    return this.requestJson(`/v1/chat/${encodeURIComponent(sessionId)}/approve`, {
      job_id: approval.jobId,
      approved: approval.approved,
      changes: approval.changes?.map((change) => ({
        change_id: change.changeId,
        approved: change.approved,
        feedback: change.feedback,
      })),
    });
  }

  async exportDocument(input: SuperDocsExportInput): Promise<Buffer> {
    if (!input.html && !input.sessionId) {
      throw new Error("SuperDocs export requires html or sessionId.");
    }

    const response = await this.request(`/v1/documents/export`, {
      method: "POST",
      body: JSON.stringify({
        html: input.html,
        session_id: input.sessionId,
        format: input.format,
        filename: input.filename,
      }),
    });
    return Buffer.from(await response.arrayBuffer());
  }

  private async requestJson(endpoint: string, payload: Record<string, unknown>): Promise<unknown> {
    const response = await this.request(endpoint, {
      method: "POST",
      body: JSON.stringify(payload),
    });
    const rawText = await response.text();
    try {
      return JSON.parse(rawText) as unknown;
    } catch {
      return rawText;
    }
  }

  private async request(endpoint: string, init: RequestInit): Promise<Response> {
    const response = await fetch(`${this.config.baseUrl.replace(/\/$/, "")}${endpoint}`, {
      ...init,
      headers: {
        "Authorization": `Bearer ${this.config.apiKey}`,
        "Content-Type": "application/json",
        ...init.headers,
      },
    });
    if (!response.ok) {
      const body = await response.text();
      throw new Error(`SuperDocs request failed (${response.status}) at ${endpoint}: ${body}`);
    }
    return response;
  }

  private async persistUsage(
    usage: SuperDocsUsage | undefined,
    operation: "chat" | "async-chat" | "job",
    sessionId?: string,
    jobId?: string,
  ): Promise<void> {
    if (!usage || !this.config.usagePath) return;
    const key = `${operation}:${sessionId ?? ""}:${jobId ?? ""}:${usage.monthlyUsed ?? ""}:${usage.operationsCharged ?? ""}`;
    if (this.recordedUsageKeys.has(key)) return;
    this.recordedUsageKeys.add(key);
    await appendUsageRecord(this.config.usagePath, {
      ...usage,
      recordedAt: new Date().toISOString(),
      operation,
      sessionId,
      jobId,
    });
  }
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

function stringOrUndefined(value: unknown): string | undefined {
  return typeof value === "string" ? value : undefined;
}

async function parseJsonResponse(response: Response): Promise<unknown> {
  const rawText = await response.text();
  try {
    return JSON.parse(rawText) as unknown;
  } catch {
    return rawText;
  }
}

function parseNestedJson(value: unknown): unknown {
  let current = value;
  for (let attempt = 0; attempt < 2 && typeof current === "string"; attempt += 1) {
    try {
      current = JSON.parse(current) as unknown;
    } catch {
      break;
    }
  }
  return current;
}
