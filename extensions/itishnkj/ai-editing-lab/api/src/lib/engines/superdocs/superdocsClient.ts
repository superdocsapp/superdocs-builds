import { EngineUnavailableError, type EngineUsage } from "../types";
import {
  buildDecisionBody,
  buildStartReviewBody,
  normalizePendingChanges,
  type SuperdocsPendingChange,
} from "./contracts";

const DEFAULT_BASE_URL = "https://api.superdocs.app/v1";
const REQUEST_TIMEOUT_MS = 30_000;

export { normalizePendingChanges, type SuperdocsPendingChange } from "./contracts";

export type SuperdocsJob = {
  status: string;
  metadata?: Record<string, unknown>;
  result?: {
    response?: string;
    document_changes?: {
      updated_html?: string;
      changes_summary?: string;
    };
    usage?: Record<string, unknown>;
  };
  error?: string | { message?: string };
};

type SuperdocsStartResponse = { job_id?: string };

function configuredApiKey(): string {
  const apiKey = process.env.SUPERDOCS_API_KEY;
  if (!apiKey) {
    throw new EngineUnavailableError(
      "SuperDocs Hosted requires SUPERDOCS_API_KEY on the server.",
    );
  }
  return apiKey;
}

function baseUrl(): string {
  return (process.env.SUPERDOCS_BASE_URL ?? DEFAULT_BASE_URL).replace(/\/+$/, "");
}

async function request<T>(path: string, init: RequestInit): Promise<T> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);
  try {
    const response = await fetch(`${baseUrl()}${path}`, {
      ...init,
      headers: {
        Authorization: `Bearer ${configuredApiKey()}`,
        "Content-Type": "application/json",
        ...(init.headers ?? {}),
      },
      signal: controller.signal,
    });
    const body = (await response.json().catch(() => ({}))) as Record<string, unknown>;
    if (!response.ok) {
      const detail =
        typeof body.detail === "string"
          ? body.detail
          : typeof body.error === "string"
            ? body.error
            : null;
      throw new Error(
        detail
          ? `SuperDocs request failed: ${detail}`
          : `SuperDocs request failed with HTTP ${response.status}.`,
      );
    }
    return body as T;
  } catch (error) {
    if (error instanceof Error && error.name === "AbortError") {
      throw new Error("SuperDocs request timed out.");
    }
    throw error;
  } finally {
    clearTimeout(timer);
  }
}

export async function startSuperdocsReview(input: {
  sessionId: string;
  documentHtml: string;
  message: string;
}): Promise<string> {
  const response = await request<SuperdocsStartResponse>("/chat/async", {
    method: "POST",
    body: JSON.stringify(
      buildStartReviewBody({
        ...input,
        modelTier: process.env.SUPERDOCS_MODEL_TIER ?? "core",
        thinkingDepth: process.env.SUPERDOCS_THINKING_DEPTH ?? "balanced",
      }),
    ),
  });
  if (!response.job_id) {
    throw new Error("SuperDocs did not return a job ID for the review request.");
  }
  return response.job_id;
}

export async function getSuperdocsJob(jobId: string): Promise<SuperdocsJob> {
  return request<SuperdocsJob>(`/jobs/${encodeURIComponent(jobId)}`, {
    method: "GET",
  });
}

export async function submitSuperdocsDecisions(input: {
  sessionId: string;
  jobId: string;
  decisions: Array<{ changeId: string; approved: boolean; feedback?: string | null }>;
}): Promise<void> {
  await request<Record<string, never>>(
    `/chat/${encodeURIComponent(input.sessionId)}/approve`,
    {
      method: "POST",
      body: JSON.stringify(buildDecisionBody(input)),
    },
  );
}

export function normalizeUsage(job: SuperdocsJob): EngineUsage | null {
  const usage = job.result?.usage;
  if (!usage) return null;
  const number = (keys: string[]) => {
    for (const key of keys) {
      const value = usage[key];
      if (typeof value === "number") return value;
    }
    return null;
  };
  return {
    inputTokens: number(["input_tokens", "prompt_tokens"]),
    outputTokens: number(["output_tokens", "completion_tokens"]),
    totalTokens: number(["total_tokens"]),
    hostedUsage: JSON.stringify(usage),
  };
}