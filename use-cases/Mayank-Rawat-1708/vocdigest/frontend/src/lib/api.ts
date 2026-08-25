/**
 * @file src/lib/api.ts
 * @description Typed client for the VocDigest backend. Every network call in the app
 *   goes through here so error handling, base-URL resolution and response shapes are
 *   defined once rather than re-derived in each component.
 * @flow request() wraps fetch, turns a non-2xx into a thrown ApiError carrying the
 *   server's detail string, and parses JSON -> the exported functions are thin, named
 *   wrappers so call sites read as intent rather than as URLs.
 * @dependencies none — deliberately dependency-free so the client stays portable
 */

// Vite proxies /api to the backend in dev; in production this is same-origin.
const BASE = import.meta.env.VITE_API_BASE ?? "/api";

export class ApiError extends Error {
  constructor(
    message: string,
    public status: number,
    public detail?: unknown,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${BASE}${path}`, {
    headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
    ...init,
  });

  if (!response.ok) {
    // Surface the backend's own message. A generic "request failed" would hide the
    // actionable part, e.g. "Conversations file not found: /nope.csv".
    let detail: unknown;
    try {
      const body = await response.json();
      detail = body?.detail ?? body;
    } catch {
      detail = await response.text().catch(() => "");
    }
    const message =
      typeof detail === "string" && detail ? detail : `Request failed (${response.status})`;
    throw new ApiError(message, response.status, detail);
  }

  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

// ---------------------------------------------------------------- types

export type RunStatus =
  | "PENDING" | "INGESTING" | "CLASSIFYING" | "EXTRACTING" | "THEMING"
  | "ANONYMIZING" | "COMPARING" | "DRAFTING" | "AWAITING_APPROVAL"
  | "APPROVED" | "UPLOADING" | "COMPLETE" | "FAILED" | "PAUSED" | "CANCELLED";

export type StageStatus = "PENDING" | "RUNNING" | "COMPLETE" | "FAILED" | "SKIPPED";

export interface RunSummary {
  id: string;
  status: RunStatus;
  current_stage: string | null;
  created_at: string;
  updated_at: string;
  quarter_label: string;
  error_message: string | null;
  export_available: boolean;
  pending_approvals: number;
}

export interface StageRecord {
  stage: string;
  status: StageStatus;
  started_at: string | null;
  completed_at: string | null;
  attempts: number;
  error: string | null;
  duration_seconds: number | null;
  groq_tokens_used: number;
  estimated_cost_usd: number;
  superdocs_operations: number;
}

export interface DecisionEntry {
  at: string;
  stage: string;
  decision: string;
  reason: string;
  metadata: Record<string, unknown>;
}

export interface RunDetail extends RunSummary {
  timeline: StageRecord[];
  decision_log: DecisionEntry[];
  summary: {
    run_id: string;
    conversations: { ingested: number; relevant: number; skipped: number };
    themes: number;
    quotes: { anonymized: number; needing_review: number };
    comparison_available: boolean;
    injection_attempts: number;
    export_path: string | null;
    error: string | null;
  };
}

export interface Quote {
  conversation_id: string;
  citation: string;
  date: string | null;
  anonymized: string;
  redaction_count: number;
  redactions: { original: string; replacement: string; category: string; confidence: number; method: string }[];
  uncertain_spans: string[];
  needs_review: boolean;
}

export interface Theme {
  id: string;
  name: string;
  description: string;
  volume_count: number;
  volume_share: number;
  volume_trend: "GREW" | "SHRANK" | "STABLE" | "NEW" | "RESOLVED" | "UNKNOWN";
  growth_rate: number | null;
  prior_quarter_count: number | null;
  prior_theme_name: string | null;
  representative_quotes: Quote[];
  evidence_refs: { conversation_id: string; file: string; line: number; citation: string }[];
  confidence_note: string | null;
}

export interface ApprovalItem {
  id: string;
  item_type: "THEME" | "QUOTE" | "FINDING" | "UPDATE";
  status: "PENDING" | "APPROVED" | "REJECTED";
  content: Record<string, any>;
  reviewer_note: string | null;
  decided_at: string | null;
  created_at: string;
}

export interface ApprovalQueue {
  run_id: string;
  total: number;
  pending: number;
  approved: number;
  rejected: number;
  gate_open: boolean;
  groups: Record<string, ApprovalItem[]>;
}

export interface CostReport {
  run_id: string;
  stages: StageRecord[];
  totals: {
    groq_tokens_used: number;
    estimated_cost_usd: number;
    superdocs_operations: number;
    duration_seconds: number;
  };
}

// ---------------------------------------------------------------- calls

export const api = {
  listRuns: () => request<RunSummary[]>("/runs"),

  getRun: (id: string) => request<RunDetail>(`/runs/${id}`),

  startRun: (body: {
    conversations_path: string;
    last_digest_path?: string | null;
    quarter_label?: string;
  }) =>
    request<{ run_id: string; status: RunStatus }>("/runs", {
      method: "POST",
      body: JSON.stringify(body),
    }),

  /** Upload path. FormData sets its own multipart boundary, so the JSON header is dropped. */
  startRunFromUpload: async (
    conversations: File,
    lastDigest: File | null,
    quarterLabel: string,
  ) => {
    const form = new FormData();
    form.append("conversations", conversations);
    if (lastDigest) form.append("last_digest", lastDigest);
    form.append("quarter_label", quarterLabel);

    const response = await fetch(`${BASE}/runs/upload`, { method: "POST", body: form });
    if (!response.ok) {
      const body = await response.json().catch(() => ({}));
      throw new ApiError(body?.detail ?? "Upload failed", response.status, body);
    }
    return (await response.json()) as { run_id: string; status: RunStatus };
  },

  /** Clear one stage's checkpoint and everything after it, then resume. */
  retryStage: (id: string, stage: string) =>
    request<{ retrying: string; invalidated: string[] }>(`/runs/${id}/stages/retry`, {
      method: "POST",
      body: JSON.stringify({ stage }),
    }),

  /** Mark a stage SKIPPED and move past it. Rejected for ingest/theme/human_gate. */
  skipStage: (id: string, stage: string) =>
    request<{ skipped: string }>(`/runs/${id}/stages/skip`, {
      method: "POST",
      body: JSON.stringify({ stage }),
    }),

  /** Stop a run consuming provider tokens. Effective at the next stage boundary. */
  cancelRun: (id: string) =>
    request<{ cancelled_from: string; tokens_spent: number; note: string }>(
      `/runs/${id}/cancel`,
      { method: "POST" },
    ),

  /** Runs currently spending against the shared provider allowance. */
  activeRuns: () =>
    request<{
      active_count: number;
      total_tokens_spent_by_active_runs: number;
      runs: { run_id: string; status: string; current_stage: string | null; tokens_spent: number }[];
    }>("/runs/active/summary"),

  resumeRun: (id: string) =>
    request<{ run_id: string; resumed_from: string }>(`/runs/${id}/resume`, { method: "POST" }),

  getThemes: (id: string) => request<Theme[]>(`/runs/${id}/themes`),

  getCost: (id: string) => request<CostReport>(`/runs/${id}/cost`),

  getApprovalItems: (id: string) => request<ApprovalQueue>(`/runs/${id}/approval-items`),

  submitDecisions: (
    id: string,
    approved: string[],
    rejected: string[],
    notes: Record<string, string> = {},
  ) =>
    request<{ approved: number; rejected: number; pending: number; resumed: boolean }>(
      `/runs/${id}/approve`,
      { method: "POST", body: JSON.stringify({ approved_ids: approved, rejected_ids: rejected, notes }) },
    ),

  approveAll: (id: string) =>
    request<{ approved: number; resumed: boolean }>(`/runs/${id}/approve-all`, { method: "POST" }),

  exportUrl: (id: string) => `${BASE}/runs/${id}/export`,
};