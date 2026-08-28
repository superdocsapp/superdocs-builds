import type {
  QueueListResponse,
  QueueItem,
  DecisionResponse,
  RunSummary,
  PipelineProgress,
} from "@/types/review";
import {
  mockFetchRuns,
  mockFetchQueue,
  mockFetchItem,
  mockSubmitDecision,
  mockFetchRunProgress,
  mockResumeRun,
} from "./mockData";

/**
 * When VITE_MOCK_API=true, all API calls return mock data.
 * Toggle in .env or .env.local: VITE_MOCK_API=true
 */
const USE_MOCK = import.meta.env.VITE_MOCK_API === "true";

/**
 * Base URL for API requests. Configurable via VITE_API_BASE_URL environment variable.
 */
const BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "";

/**
 * Typed API error with classification for downstream handling.
 */
export class ApiError extends Error {
  type: "not_found" | "conflict" | "server_error" | "network_error";
  status?: number;

  constructor(
    message: string,
    type: "not_found" | "conflict" | "server_error" | "network_error",
    status?: number
  ) {
    super(message);
    this.name = "ApiError";
    this.type = type;
    this.status = status;
  }
}

/**
 * Classifies an HTTP response into an ApiError if the status is not OK.
 * Throws the classified error so callers only receive successful data.
 */
async function handleResponse<T>(response: Response): Promise<T> {
  if (response.ok) {
    return response.json() as Promise<T>;
  }

  const status = response.status;

  if (status === 404) {
    throw new ApiError("Resource not found", "not_found", status);
  }

  if (status === 409) {
    throw new ApiError("Resource conflict", "conflict", status);
  }

  if (status >= 500) {
    throw new ApiError("Server error", "server_error", status);
  }

  // Catch-all for other client errors (4xx) — treat as server_error
  throw new ApiError(
    `Unexpected error (${status})`,
    "server_error",
    status
  );
}

/**
 * Wraps fetch to catch network failures and reclassify them as ApiError.
 */
async function safeFetch(
  url: string,
  options?: RequestInit
): Promise<Response> {
  try {
    return await fetch(url, options);
  } catch {
    throw new ApiError(
      "Network request failed",
      "network_error"
    );
  }
}

// ─── Public API Functions ────────────────────────────────────────────────────

/**
 * Fetches the approval queue for a given run.
 * GET /approval/runs/{run_id}/queue
 */
export async function fetchQueue(runId: string): Promise<QueueListResponse> {
  if (USE_MOCK) return mockFetchQueue(runId);
  const response = await safeFetch(`${BASE_URL}/approval/runs/${runId}/queue`);
  return handleResponse<QueueListResponse>(response);
}

/**
 * Fetches all pending approval items across all runs.
 * GET /approval/pending
 */
export async function fetchAllPending(): Promise<QueueListResponse> {
  if (USE_MOCK) return mockFetchQueue("all");
  const response = await safeFetch(`${BASE_URL}/approval/pending`);
  const data = await handleResponse<{ items: QueueListResponse["items"]; total: number }>(response);
  return {
    run_id: "all",
    items: data.items,
    total: data.total,
    pending: data.total,
  };
}

/**
 * Fetches a single queue item by ID.
 * GET /approval/items/{item_id}
 */
export async function fetchItem(itemId: string): Promise<QueueItem> {
  if (USE_MOCK) return mockFetchItem(itemId);
  const response = await safeFetch(`${BASE_URL}/approval/items/${itemId}`);
  return handleResponse<QueueItem>(response);
}

/**
 * Submits an approval/rejection decision for a queue item.
 * POST /approval/items/{item_id}/decide
 */
export async function submitDecision(
  itemId: string,
  request: {
    decision: "approved" | "rejected";
    reviewer_id: string;
    justification: string;
  }
): Promise<DecisionResponse> {
  if (USE_MOCK) return mockSubmitDecision(itemId, request);
  const response = await safeFetch(
    `${BASE_URL}/approval/items/${itemId}/decide`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(request),
    }
  );
  return handleResponse<DecisionResponse>(response);
}

/**
 * Fetches all available pipeline runs.
 * GET /runs
 */
export async function fetchRuns(): Promise<RunSummary[]> {
  if (USE_MOCK) return mockFetchRuns();
  const response = await safeFetch(`${BASE_URL}/runs`);
  return handleResponse<RunSummary[]>(response);
}

/**
 * Resumes a paused pipeline run.
 * POST /runs/{run_id}/resume
 */
export async function resumeRun(runId: string): Promise<unknown> {
  if (USE_MOCK) return mockResumeRun(runId);
  const response = await safeFetch(`${BASE_URL}/runs/${runId}/resume`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
  });
  return handleResponse<unknown>(response);
}

/**
 * Fetches pipeline progress/history for a run.
 * GET /runs/{run_id}/history
 */
export async function fetchRunProgress(
  runId: string
): Promise<PipelineProgress> {
  if (USE_MOCK) return mockFetchRunProgress(runId);
  const response = await safeFetch(`${BASE_URL}/runs/${runId}/history`);
  return handleResponse<PipelineProgress>(response);
}
