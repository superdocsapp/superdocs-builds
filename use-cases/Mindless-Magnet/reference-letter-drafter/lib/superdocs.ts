import "server-only";
import { request, requestJson } from "./http";
import type {
  ChatAsyncResponse,
  JobStatusResponse,
  SuperDocsTemplate,
  UploadResponse,
  UsageStatus,
} from "./types";

/**
 * The SuperDocs client. Every call goes through `request`, so every call gets a
 * deadline, bounded retry on transient failures only, and an error that names
 * the cause and the fix.
 *
 * Timeouts are per-operation and deliberately uneven. A draft job returns a job
 * id immediately, so 30s is generous. An export renders a real .docx and is
 * allowed 120s. Polling is short: if a poll is slow, the next poll will do.
 */

const BASE_URL = process.env.SUPERDOCS_BASE_URL?.replace(/\/$/, "") ?? "https://api.superdocs.app/v1";

function apiKey(): string {
  const key = process.env.SUPERDOCS_API_KEY;
  if (!key) {
    throw new Error(
      "SUPERDOCS_API_KEY is not set. Copy .env.local.example to .env.local and add your key from use.superdocs.app.",
    );
  }
  return key;
}

function authHeaders(): Record<string, string> {
  return { Authorization: `Bearer ${apiKey()}` };
}

function jsonHeaders(): Record<string, string> {
  return { ...authHeaders(), "Content-Type": "application/json" };
}

export async function uploadStarterDocument(sessionId: string): Promise<UploadResponse> {
  const starterHtml = "<h1>Reference Letter</h1><p>[placeholder]</p>";
  const form = new FormData();
  form.append("file", new Blob([starterHtml], { type: "text/html" }), "starter.html");
  form.append("session_id", sessionId);

  return requestJson<UploadResponse>(`${BASE_URL}/documents/upload`, {
    operation: "document upload",
    method: "POST",
    headers: authHeaders(),
    body: form,
    timeoutMs: 60_000,
    retries: 2,
  });
}

export async function startDraftJob(params: {
  sessionId: string;
  message: string;
  memoryKey: string;
  templateId?: string;
}): Promise<ChatAsyncResponse> {
  return requestJson<ChatAsyncResponse>(`${BASE_URL}/chat/async`, {
    operation: "start draft",
    method: "POST",
    headers: jsonHeaders(),
    timeoutMs: 30_000,
    // A draft costs an operation. Retrying a request that may already have been
    // accepted upstream is how you get billed twice for one letter, so this
    // path does not retry; the route's idempotency key handles the client
    // clicking twice, and a genuine 5xx is surfaced for the human to re-run.
    retries: 0,
    body: JSON.stringify({
      message: params.message,
      session_id: params.sessionId,
      approval_mode: "ask_every_time",
      cross_session_memory: true,
      cross_session_memory_key: params.memoryKey,
      ...(params.templateId ? { template_id: params.templateId } : {}),
    }),
  });
}

export async function getJobStatus(jobId: string): Promise<JobStatusResponse> {
  return requestJson<JobStatusResponse>(`${BASE_URL}/jobs/${encodeURIComponent(jobId)}`, {
    operation: "job status",
    headers: authHeaders(),
    cache: "no-store",
    timeoutMs: 15_000,
    retries: 1,
  });
}

export async function approveChanges(params: {
  sessionId: string;
  jobId: string;
  changes: { change_id: string; approved: boolean; feedback?: string }[];
}): Promise<{ status: string; message: string; batch_complete?: boolean }> {
  return requestJson(`${BASE_URL}/chat/${encodeURIComponent(params.sessionId)}/approve`, {
    operation: "approve changes",
    method: "POST",
    headers: jsonHeaders(),
    timeoutMs: 60_000,
    retries: 0,
    body: JSON.stringify({
      job_id: params.jobId,
      // Required by the API even for per-change batches: it is the default for
      // any entry that omits its own `approved`. Every entry here sets its own.
      approved: true,
      changes: params.changes,
    }),
  });
}

/**
 * Answer the "this edit is large, keep going?" prompt.
 *
 * Wired because the alternative was a dead end that told the user to shorten
 * their letter, and a path that is present but broken is worse than one that is
 * honestly absent.
 */
export async function continueJob(params: {
  sessionId: string;
  jobId: string;
  proceed: boolean;
}): Promise<{ status: string }> {
  return requestJson(`${BASE_URL}/chat/${encodeURIComponent(params.sessionId)}/continue`, {
    operation: "continue draft",
    method: "POST",
    headers: jsonHeaders(),
    timeoutMs: 30_000,
    retries: 0,
    body: JSON.stringify({ job_id: params.jobId, continue: params.proceed }),
  });
}

export async function exportDocument(params: {
  sessionId: string;
  filename: string;
}): Promise<{ body: ArrayBuffer; contentType: string; warnings: unknown[] }> {
  const res = await request(`${BASE_URL}/documents/export`, {
    operation: "export document",
    method: "POST",
    headers: jsonHeaders(),
    // Exports do not cost operations, so retrying one is free and safe.
    timeoutMs: 120_000,
    retries: 2,
    body: JSON.stringify({
      session_id: params.sessionId,
      format: "docx",
      options: { filename: params.filename },
    }),
  });

  let warnings: unknown[] = [];
  const header = res.headers.get("X-Export-Warnings");
  if (header) {
    try {
      warnings = JSON.parse(Buffer.from(header, "base64").toString("utf-8"));
    } catch {
      // A malformed warnings header must not lose the document the user is
      // waiting for. Note it and carry on.
      warnings = [{ note: "Export warnings header could not be decoded." }];
    }
  }

  return {
    body: await res.arrayBuffer(),
    contentType:
      res.headers.get("Content-Type") ??
      "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    warnings,
  };
}

export async function listTemplates(): Promise<SuperDocsTemplate[]> {
  const data = await requestJson<{ templates?: SuperDocsTemplate[] } | SuperDocsTemplate[]>(
    `${BASE_URL}/templates`,
    {
      operation: "list templates",
      headers: authHeaders(),
      cache: "no-store",
      timeoutMs: 15_000,
      retries: 1,
    },
  );
  return Array.isArray(data) ? data : (data.templates ?? []);
}

export async function uploadTemplate(file: File): Promise<SuperDocsTemplate> {
  const form = new FormData();
  form.append("file", file);
  return requestJson<SuperDocsTemplate>(`${BASE_URL}/templates/upload`, {
    operation: "template upload",
    method: "POST",
    headers: authHeaders(),
    body: form,
    timeoutMs: 60_000,
    retries: 1,
  });
}

/**
 * Remaining operation budget.
 *
 * Shown in the UI before a draft is started, because a free tier that runs out
 * halfway through a demo is a bad surprise, and because "it knows what it cost"
 * is only meaningful if you can see the number before you spend it.
 */
export async function getUsage(): Promise<UsageStatus> {
  try {
    const data = await requestJson<Record<string, unknown>>(`${BASE_URL}/users/limits`, {
      operation: "usage check",
      headers: authHeaders(),
      cache: "no-store",
      timeoutMs: 10_000,
      retries: 1,
    });

    const num = (...keys: string[]): number | undefined => {
      for (const key of keys) {
        const value = data[key];
        if (typeof value === "number") return value;
      }
      return undefined;
    };

    const remaining = num("operations_remaining", "remaining_operations", "remaining");
    return {
      tier: typeof data.tier === "string" ? data.tier : undefined,
      operationsUsed: num("operations_used", "used_operations", "used"),
      operationsRemaining: remaining,
      lowBudget: typeof remaining === "number" && remaining <= 3,
    };
  } catch {
    // Usage is advisory. Never block a draft because the meter is unreadable.
    return { lowBudget: false };
  }
}
