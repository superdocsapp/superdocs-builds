import { randomUUID } from "node:crypto";
import {
  EngineUnavailableError,
  type EditingEngine,
  type EngineEditRequest,
  type EngineEditResult,
  type HostedReviewEngine,
  type ReviewDecisionRequest,
} from "../types";
import { validateDocumentHtml } from "../validation";

const SUPERDOCS_PROMPT_VERSION = "superdocs-hosted-v1";
const DEFAULT_BASE_URL = "https://api.superdocs.app";
const DEFAULT_POLL_INTERVAL_MS = 500;
const DEFAULT_POLL_ATTEMPTS = 120;

type FetchLike = typeof fetch;

type SuperdocsJob = {
  job_id?: string;
  session_id?: string;
  status?: string;
  result?: {
    response?: string;
    session_id?: string;
    document_changes?: {
      updated_html?: string;
      version_id?: string;
      changes_summary?: string;
    };
    usage?: unknown;
  };
  metadata?: {
    awaiting_kind?: string;
    pending_changes?: Array<{
      change_id?: string;
      operation?: string;
      chunk_id?: string | null;
      old_html?: string | null;
      new_html?: string | null;
      ai_explanation?: string | null;
      insert_after_chunk_id?: string | null;
    }>;
  };
  error?: unknown;
};

type PendingReview = {
  jobId: string;
  sessionId: string;
  request: EngineEditRequest;
  startedAt: Date;
  batchNumber: number;
  reviewWaitMs: number;
  pausedAt: Date | null;
};

export type SuperdocsEngineOptions = {
  fetchImpl?: FetchLike;
  sleep?: (milliseconds: number) => Promise<void>;
  env?: NodeJS.ProcessEnv;
};

function wait(milliseconds: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, milliseconds));
}

function envInteger(
  value: string | undefined,
  fallback: number,
  maximum: number,
): number {
  const parsed = Number(value);
  if (!Number.isInteger(parsed) || parsed < 1) return fallback;
  return Math.min(parsed, maximum);
}

function selectedSettings(env: NodeJS.ProcessEnv) {
  const modelTier = env.SUPERDOCS_MODEL_TIER ?? "core";
  const thinkingDepth = env.SUPERDOCS_THINKING_DEPTH ?? "balanced";
  if (!["core", "turbo", "pro", "max"].includes(modelTier)) {
    throw new EngineUnavailableError("SUPERDOCS_MODEL_TIER is not supported.");
  }
  if (!["fast", "balanced", "deep"].includes(thinkingDepth)) {
    throw new EngineUnavailableError(
      "SUPERDOCS_THINKING_DEPTH is not supported.",
    );
  }
  return { modelTier, thinkingDepth };
}

export function getSuperdocsPublicConfig(env = process.env) {
  const configured = Boolean(env.SUPERDOCS_API_KEY);
  const settings = selectedSettings(env);
  return {
    configured,
    modelTier: settings.modelTier,
    thinkingDepth: settings.thinkingDepth,
    modelLabel: `${settings.modelTier} · ${settings.thinkingDepth}`,
  };
}

function asRecord(value: unknown): Record<string, unknown> | null {
  return value && typeof value === "object"
    ? (value as Record<string, unknown>)
    : null;
}

function safeProviderMessage(value: unknown): string {
  const record = asRecord(value);
  const message =
    (record?.message as string | undefined) ??
    (record?.error as string | undefined) ??
    (typeof value === "string" ? value : "");
  return /api.?key|authorization|bearer|token|secret/i.test(message)
    ? "SuperDocs rejected the request. Check the server-side configuration."
    : "SuperDocs could not process this request.";
}

export class SuperdocsEngine implements HostedReviewEngine {
  readonly id = "superdocs" as const;
  readonly label = "SuperDocs Hosted";
  private readonly fetchImpl: FetchLike;
  private readonly sleep: (milliseconds: number) => Promise<void>;
  private readonly env: NodeJS.ProcessEnv;
  private readonly reviews = new Map<string, PendingReview>();

  constructor(options: SuperdocsEngineOptions = {}) {
    this.fetchImpl = options.fetchImpl ?? fetch;
    this.sleep = options.sleep ?? wait;
    this.env = options.env ?? process.env;
  }

  async edit(request: EngineEditRequest): Promise<EngineEditResult> {
    const safeRequest = {
      ...request,
      documentHtml: validateDocumentHtml(request.documentHtml),
      selectionHtml: request.selectionHtml
        ? validateDocumentHtml(request.selectionHtml)
        : request.selectionHtml,
    };
    const apiKey = this.env.SUPERDOCS_API_KEY;
    if (!apiKey) {
      throw new EngineUnavailableError(
        "SuperDocs is not configured. Add SUPERDOCS_API_KEY through Replit Secrets.",
      );
    }

    const settings = selectedSettings(this.env);
    const startedAt = new Date();
    const sessionId = `lab-${safeRequest.requestId}`;
    const job = await this.requestJson<SuperdocsJob>("/v1/chat/async", {
      method: "POST",
      body: {
        message: this.messageFor(safeRequest),
        session_id: sessionId,
        document_html: safeRequest.documentHtml,
        approval_mode: "ask_every_time",
        model_tier: settings.modelTier,
        thinking_depth: settings.thinkingDepth,
      },
    });

    if (!job.job_id) {
      throw new Error("SuperDocs did not return a review job.");
    }
    return this.poll({
      jobId: job.job_id,
      sessionId: job.session_id ?? sessionId,
      request: safeRequest,
      startedAt,
      batchNumber: 1,
      reviewWaitMs: 0,
      pausedAt: null,
    });
  }

  async decideReview(
    request: ReviewDecisionRequest,
  ): Promise<EngineEditResult> {
    const review = this.reviews.get(request.reviewId);
    if (!review) {
      throw new EngineUnavailableError(
        "This hosted review is no longer available. Generate the proposal again.",
      );
    }
    const ids = [...new Set(request.changeIds)].filter(Boolean);
    if (!ids.length) {
      throw new Error("Choose at least one proposed change.");
    }
    const approved = request.decision === "accept";
    const continuedReview = {
      ...review,
      batchNumber: review.batchNumber + 1,
      reviewWaitMs:
        review.reviewWaitMs +
        (review.pausedAt ? Date.now() - review.pausedAt.getTime() : 0),
      pausedAt: null,
    };
    this.reviews.set(request.reviewId, continuedReview);
    await this.requestJson(`/v1/chat/${encodeURIComponent(review.sessionId)}/approve`, {
      method: "POST",
      body: {
        job_id: review.jobId,
        approved,
        changes: ids.map((changeId) => ({ change_id: changeId, approved })),
      },
    });
    return this.poll(continuedReview, request.reviewId);
  }

  async cancelReview(reviewId: string): Promise<EngineEditResult> {
    const review = this.reviews.get(reviewId);
    if (!review) {
      throw new EngineUnavailableError(
        "This hosted review is no longer available. Generate the proposal again.",
      );
    }
    await this.requestJson(
      `/v1/jobs/${encodeURIComponent(review.jobId)}/cancel`,
      { method: "POST" },
    );
    this.reviews.delete(reviewId);
    return this.resultForCancelledReview(review);
  }

  private async poll(
    review: PendingReview,
    existingReviewId?: string,
  ): Promise<EngineEditResult> {
    const attempts = envInteger(
      this.env.SUPERDOCS_POLL_ATTEMPTS,
      DEFAULT_POLL_ATTEMPTS,
      240,
    );
    const intervalMs = envInteger(
      this.env.SUPERDOCS_POLL_INTERVAL_MS,
      DEFAULT_POLL_INTERVAL_MS,
      5_000,
    );
    for (let attempt = 0; attempt < attempts; attempt += 1) {
      let job: SuperdocsJob;
      try {
        job = await this.requestJson<SuperdocsJob>(
          `/v1/jobs/${encodeURIComponent(review.jobId)}`,
        );
      } catch (error) {
        await this.cancelPollingReview(review, existingReviewId);
        throw error;
      }
      if (job.status === "awaiting_approval") {
        if (job.metadata?.awaiting_kind === "continue_prompt") {
          await this.cancelPollingReview(review, existingReviewId);
          throw new Error(
            "SuperDocs paused a large edit for continuation, which this review lab does not auto-continue.",
          );
        }
        const proposedChanges = (job.metadata?.pending_changes ?? []).map(
          (change) => {
            const oldHtml = change.old_html
              ? validateDocumentHtml(change.old_html)
              : null;
            const newHtml = change.new_html
              ? validateDocumentHtml(change.new_html)
              : null;
            return {
              id: change.change_id ?? randomUUID(),
              operation: this.operation(change.operation),
              oldHtml,
              newHtml,
              explanation: change.ai_explanation ?? null,
              target: change.insert_after_chunk_id ?? change.chunk_id ?? null,
              chunkId: change.chunk_id ?? null,
              status: "pending" as const,
            };
          },
        );
        if (!proposedChanges.length) {
          await this.cancelPollingReview(review, existingReviewId);
          throw new Error("SuperDocs paused without a reviewable change batch.");
        }
        const reviewId = existingReviewId ?? randomUUID();
        const pausedReview = { ...review, pausedAt: new Date() };
        this.reviews.set(reviewId, pausedReview);
        return this.resultForReview(pausedReview, reviewId, proposedChanges);
      }
      if (job.status === "completed") {
        if (existingReviewId) this.reviews.delete(existingReviewId);
        return this.resultForCompletedJob(review, job);
      }
      if (job.status === "cancelled") {
        if (existingReviewId) this.reviews.delete(existingReviewId);
        return this.resultForCancelledReview(review);
      }
      if (job.status === "failed") {
        if (existingReviewId) this.reviews.delete(existingReviewId);
        throw new Error(safeProviderMessage(job.error));
      }
      if (attempt < attempts - 1) await this.sleep(intervalMs);
    }
    await this.cancelPollingReview(review, existingReviewId);
    throw new Error("SuperDocs is still processing this review. The job was cancelled.");
  }

  private async requestJson<T = unknown>(
    path: string,
    options: { method?: "GET" | "POST"; body?: unknown } = {},
  ): Promise<T> {
    const apiKey = this.env.SUPERDOCS_API_KEY;
    if (!apiKey) {
      throw new EngineUnavailableError(
        "SuperDocs is not configured. Add SUPERDOCS_API_KEY through Replit Secrets.",
      );
    }
    const baseUrl = (this.env.SUPERDOCS_BASE_URL ?? DEFAULT_BASE_URL).replace(
      /\/$/,
      "",
    );
    let response: Response;
    try {
      response = await this.fetchImpl(`${baseUrl}${path}`, {
        method: options.method ?? "GET",
        headers: {
          Authorization: `Bearer ${apiKey}`,
          ...(options.body ? { "Content-Type": "application/json" } : {}),
        },
        ...(options.body ? { body: JSON.stringify(options.body) } : {}),
      });
    } catch {
      throw new Error("SuperDocs could not be reached. Try again shortly.");
    }
    const content = await response.text();
    let payload: unknown = null;
    try {
      payload = content ? JSON.parse(content) : null;
    } catch {
      payload = content;
    }
    if (!response.ok) {
      throw new Error(safeProviderMessage(payload));
    }
    return payload as T;
  }

  private messageFor(request: EngineEditRequest): string {
    if (request.scope !== "selection") return request.instruction;
    return `${request.instruction}\n\nEdit only the selected content: ${request.selectionText ?? ""}`;
  }

  private operation(value: string | undefined): "edit" | "create" | "delete" {
    return value === "create" || value === "delete" ? value : "edit";
  }

  private async cancelJobSilently(jobId: string): Promise<void> {
    try {
      await this.requestJson(`/v1/jobs/${encodeURIComponent(jobId)}/cancel`, {
        method: "POST",
      });
    } catch {
      // The original bounded-polling error is safer and more actionable here.
    }
  }

  private async cancelPollingReview(
    review: PendingReview,
    reviewId?: string,
  ): Promise<void> {
    await this.cancelJobSilently(review.jobId);
    if (reviewId) this.reviews.delete(reviewId);
  }

  private resultForReview(
    review: PendingReview,
    reviewId: string,
    proposedChanges: EngineEditResult["proposedChanges"],
  ): EngineEditResult {
    const completedAt = new Date();
    return {
      engine: this.id,
      engineLabel: this.label,
      promptVersion: SUPERDOCS_PROMPT_VERSION,
      requestId: review.request.requestId,
      success: true,
      proposedChanges,
      candidateDocumentHtml: null,
      assistantMessage: "SuperDocs has proposed changes for your review.",
      latencyMs: this.providerProcessingMs(review, completedAt),
      reviewWaitMs: review.reviewWaitMs,
      usage: null,
      retryCount: 0,
      requestMetrics: this.requestMetrics(review),
      error: null,
      review: {
        reviewId,
        state: "awaiting_approval",
        batchNumber: review.batchNumber,
      },
      startedAt: review.startedAt.toISOString(),
      completedAt: completedAt.toISOString(),
    };
  }

  private resultForCompletedJob(
    review: PendingReview,
    job: SuperdocsJob,
  ): EngineEditResult {
    const completedAt = new Date();
    const documentHtml = job.result?.document_changes?.updated_html
      ? validateDocumentHtml(job.result.document_changes.updated_html)
      : null;
    return {
      engine: this.id,
      engineLabel: this.label,
      promptVersion: SUPERDOCS_PROMPT_VERSION,
      requestId: review.request.requestId,
      success: true,
      proposedChanges: [],
      candidateDocumentHtml: documentHtml,
      assistantMessage:
        job.result?.response ??
        job.result?.document_changes?.changes_summary ??
        null,
      latencyMs: this.providerProcessingMs(review, completedAt),
      reviewWaitMs: review.reviewWaitMs,
      usage: job.result?.usage
        ? {
            inputTokens: null,
            outputTokens: null,
            totalTokens: null,
            hostedUsage: JSON.stringify(job.result.usage),
          }
        : null,
      retryCount: 0,
      requestMetrics: this.requestMetrics(review),
      error: null,
      review: null,
      startedAt: review.startedAt.toISOString(),
      completedAt: completedAt.toISOString(),
    };
  }

  private resultForCancelledReview(review: PendingReview): EngineEditResult {
    const completedAt = new Date();
    return {
      engine: this.id,
      engineLabel: this.label,
      promptVersion: SUPERDOCS_PROMPT_VERSION,
      requestId: review.request.requestId,
      success: false,
      proposedChanges: [],
      candidateDocumentHtml: null,
      assistantMessage: "The SuperDocs review was cancelled.",
      latencyMs: this.providerProcessingMs(review, completedAt),
      reviewWaitMs: review.reviewWaitMs,
      usage: null,
      retryCount: 0,
      requestMetrics: this.requestMetrics(review),
      error: "Review cancelled.",
      review: null,
      startedAt: review.startedAt.toISOString(),
      completedAt: completedAt.toISOString(),
    };
  }

  private providerProcessingMs(review: PendingReview, completedAt: Date): number {
    const activeWait =
      review.pausedAt ? completedAt.getTime() - review.pausedAt.getTime() : 0;
    return Math.max(
      0,
      completedAt.getTime() -
        review.startedAt.getTime() -
        review.reviewWaitMs -
        activeWait,
    );
  }

  private requestMetrics(review: PendingReview) {
    return {
      promptChars: null,
      contextChars: review.request.documentHtml.length,
    };
  }
}

export const superdocsEngine = new SuperdocsEngine();