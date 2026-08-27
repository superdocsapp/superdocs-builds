import { z } from "zod";
import { getConfig, requireApiKey, type ModelTier } from "./config.js";
import { TokenScopeError } from "./errors.js";

/**
 * The SuperDocs REST client. The only module that makes network calls.
 *
 * Verified against https://api.superdocs.app/openapi.json (Universal Document AI
 * API 2.0.0). TokenScope uses four of its endpoints:
 *
 *   GET  /v1/agents/whoami          tier + monthly operation quota
 *   POST /v1/chat/async             start an edit, returns a job_id
 *   GET  /v1/jobs/{job_id}          poll: status, pending changes, token cost
 *   POST /v1/chat/{sid}/approve     apply one proposed change
 *
 * The synchronous POST /v1/chat would be a shorter path, but it returns before
 * there is a job record to read. The async job is what carries
 * `metadata.cumulative_tokens`, and that number is the product.
 */

const QuotaSchema = z.object({
  monthly_limit: z.number(),
  used: z.number(),
  remaining: z.number(),
  resets_at: z.string().nullable().optional()
});

const WhoamiSchema = z
  .object({ tier: z.string().optional(), quota: QuotaSchema.optional() })
  .passthrough();

const ChatAsyncSchema = z
  .object({ job_id: z.string(), session_id: z.string(), status: z.string().optional() })
  .passthrough();

const PendingChangeSchema = z
  .object({
    change_id: z.string(),
    chunk_id: z.string().nullish(),
    operation: z.string().nullish(),
    old_html: z.string().nullish(),
    new_html: z.string().nullish(),
    ai_explanation: z.string().nullish()
  })
  .passthrough();

/**
 * `cumulative_tokens` is not in the published OpenAPI schema: JobMetadata is
 * declared with additionalProperties: true and this field arrives inside it. It
 * is present on every completed chat job observed against the live API. It is
 * read defensively - absent means "not reported", never zero.
 */
const JobSchema = z
  .object({
    job_id: z.string(),
    session_id: z.string().optional(),
    status: z.string(),
    progress: z.number().nullish(),
    error: z.unknown().optional(),
    metadata: z
      .object({
        cumulative_tokens: z.number().nullish(),
        pending_changes: z.array(PendingChangeSchema).nullish()
      })
      .passthrough()
      .nullish(),
    result: z.unknown().optional()
  })
  .passthrough();

export type Job = z.infer<typeof JobSchema>;
export type PendingChange = z.infer<typeof PendingChangeSchema>;

export const TERMINAL = new Set(["completed", "succeeded", "failed", "cancelled"]);
export const PAUSED = new Set(["awaiting_approval"]);

const REQUEST_TIMEOUT_MS = 120_000;
const MAX_RETRIES = 3;

function backoff(attempt: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, 500 * 2 ** attempt));
}

async function call<T>(
  path: string,
  schema: z.ZodType<T>,
  init: { method?: "GET" | "POST"; json?: unknown } = {}
): Promise<T> {
  const key = requireApiKey();
  const { baseUrl } = getConfig();
  const method = init.method ?? "GET";

  // Minted once and reused across retries, so a retried POST cannot bill twice.
  const idempotencyKey = `ts_${crypto.randomUUID()}`;

  const request: RequestInit = {
    method,
    headers: {
      Accept: "application/json",
      Authorization: `Bearer ${key}`,
      ...(init.json === undefined ? {} : { "Content-Type": "application/json" }),
      ...(method === "POST" ? { "Idempotency-Key": idempotencyKey } : {})
    },
    ...(init.json === undefined ? {} : { body: JSON.stringify(init.json) }),
    signal: AbortSignal.timeout(REQUEST_TIMEOUT_MS)
  };

  let text = "";
  let lastError: TokenScopeError | undefined;

  /**
   * Retry the faults that are the gateway's rather than ours.
   *
   * A 503 on a poll is not a failed job: a 300-page run in the benchmark was
   * lost at 99% to exactly that. Rate limits, gateway errors and dropped
   * connections are retried; a 401 or a 400 is not, because retrying it would
   * only produce the same answer more slowly.
   */
  for (let attempt = 0; ; attempt += 1) {
    let status: number;

    try {
      // Reading the body is inside the try on purpose: the request timeout can
      // fire while a large job record is still streaming, and that rejection has
      // to be mapped like any other timeout rather than escaping as a raw
      // DOMException.
      const response = await fetch(`${baseUrl}${path}`, {
        ...request,
        signal: AbortSignal.timeout(REQUEST_TIMEOUT_MS)
      });

      status = response.status;
      text = await response.text();
    } catch (error) {
      const timedOut = error instanceof Error && error.name === "TimeoutError";

      lastError = new TokenScopeError(
        timedOut ? "timeout" : "upstream_error",
        timedOut
          ? `SuperDocs did not answer ${method} ${path} within ${REQUEST_TIMEOUT_MS / 1000}s.`
          : `Could not reach SuperDocs (${method} ${path}).`,
        {
          hint: timedOut
            ? "Very large documents can outrun the request timeout. Retry, or use a smaller document."
            : "Check network access to api.superdocs.app, then try again."
        }
      );

      if (attempt >= MAX_RETRIES) throw lastError;

      await backoff(attempt);
      continue;
    }

    if (status >= 200 && status < 300) break;

    lastError = upstreamError(status, path, text);

    if (!(status >= 500 || status === 429) || attempt >= MAX_RETRIES) throw lastError;

    await backoff(attempt);
  }

  let parsed: unknown;

  try {
    parsed = JSON.parse(text);
  } catch {
    throw new TokenScopeError(
      "unexpected_response",
      `SuperDocs returned a non-JSON body for ${method} ${path}.`,
      { hint: `First bytes: ${text.slice(0, 120)}` }
    );
  }

  const result = schema.safeParse(parsed);

  if (!result.success) {
    throw new TokenScopeError(
      "unexpected_response",
      `SuperDocs returned a body TokenScope did not recognise for ${method} ${path}.`,
      { hint: result.error.issues.map((i) => `${i.path.join(".")}: ${i.message}`).join("; ") }
    );
  }

  return result.data;
}

function upstreamError(status: number, path: string, body: string): TokenScopeError {
  const detail = body.slice(0, 300);

  if (status === 401 || status === 403) {
    return new TokenScopeError("auth_failed", "SuperDocs rejected the API key.", {
      hint: "Check SUPERDOCS_API_KEY in .env.local. Keys start with sk_ or lce_."
    });
  }

  if (status === 429) {
    return new TokenScopeError("quota_exhausted", "SuperDocs monthly operation quota is used up.", {
      hint: "The counter resets at the start of the month, or upgrade the plan."
    });
  }

  return new TokenScopeError("upstream_error", `SuperDocs returned ${status} for ${path}.`, {
    ...(detail.length > 0 ? { hint: detail } : {})
  });
}

export async function whoami(): Promise<z.infer<typeof WhoamiSchema>> {
  return call("/agents/whoami", WhoamiSchema);
}

export interface StartEditOptions {
  sessionId: string;
  message: string;
  documentHtml: string;
  modelTier?: ModelTier;
}

/**
 * Start an edit.
 *
 * `approval_mode: "ask_every_time"` is not a preference, it is the contract: the
 * job stops at `awaiting_approval` and the document is not modified until the
 * user approves a named change. TokenScope never sends approve_all.
 */
export async function startEdit(options: StartEditOptions): Promise<{ jobId: string }> {
  const started = await call("/chat/async", ChatAsyncSchema, {
    method: "POST",
    json: {
      session_id: options.sessionId,
      message: options.message,
      document_html: options.documentHtml,
      approval_mode: "ask_every_time",
      response_mode: "compact",
      model_tier: options.modelTier ?? getConfig().modelTier
    }
  });

  return { jobId: started.job_id };
}

/**
 * Read a job.
 *
 * `compact` omits the result body and the streamed progress events, leaving the
 * status, progress and pending-change ids. On a 300-page regeneration the full
 * record is megabytes of proposed HTML, and pulling it on every poll is what the
 * API's own guidance says not to do: poll compact, then read once in full.
 */
export async function getJob(jobId: string, compact = false): Promise<Job> {
  const query = compact ? "?compact=true" : "";
  return call(`/jobs/${encodeURIComponent(jobId)}${query}`, JobSchema);
}

export interface PollOptions {
  timeoutMs?: number;
  intervalMs?: number;
  onProgress?: (job: Job) => void;
}

/** Poll until the job stops moving: terminal, or paused for approval. */
export async function waitForJob(jobId: string, options: PollOptions = {}): Promise<Job> {
  const timeoutMs = options.timeoutMs ?? 900_000;
  const intervalMs = options.intervalMs ?? 2_000;
  const deadline = Date.now() + timeoutMs;

  for (;;) {
    const job = await getJob(jobId, true);
    options.onProgress?.(job);

    if (job.status === "failed" || job.status === "cancelled") {
      throw new TokenScopeError("job_failed", `SuperDocs job ${job.status}.`, {
        hint:
          typeof job.error === "string" ? job.error : JSON.stringify(job.error ?? {}).slice(0, 300)
      });
    }

    // Settled: now, and only now, pay for the full record with the changes in it.
    if (TERMINAL.has(job.status) || PAUSED.has(job.status)) return getJob(jobId);

    if (Date.now() >= deadline) {
      throw new TokenScopeError(
        "timeout",
        `SuperDocs job ${jobId} was still ${job.status} after ${Math.round(timeoutMs / 1000)}s.`,
        { hint: "Large documents take longer. Raise the timeout or shorten the selection." }
      );
    }

    await new Promise((resolve) => setTimeout(resolve, intervalMs));
  }
}

/**
 * Approve or deny one proposed change. This is the point at which the document
 * changes, and it only ever happens because the user asked for it.
 *
 * ApprovalRequest requires job_id; change_id narrows the decision to a single
 * change rather than the whole pending batch.
 */
export async function decideChange(options: {
  sessionId: string;
  jobId: string;
  changeId: string;
  approved: boolean;
}): Promise<void> {
  await call(`/chat/${encodeURIComponent(options.sessionId)}/approve`, z.object({}).passthrough(), {
    method: "POST",
    json: { job_id: options.jobId, change_id: options.changeId, approved: options.approved }
  });
}

/** The token cost SuperDocs reported for a job, or undefined if it reported none. */
export function reportedTokens(job: Job): number | undefined {
  const value = job.metadata?.cumulative_tokens;
  return typeof value === "number" ? value : undefined;
}

export function pendingChanges(job: Job): PendingChange[] {
  return job.metadata?.pending_changes ?? [];
}
