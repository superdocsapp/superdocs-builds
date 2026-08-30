/**
 * Thin, typed client for the real SuperDocs REST API (docs.superdocs.app).
 * Endpoints and field names here are transcribed from that documentation —
 * see docs/IMPLEMENTATION_PLAN.md §3 for how each one is used.
 *
 * Deliberately dependency-free (plain `fetch`, available in Node 18+) and
 * deliberately dumb: this module's only job is shaping HTTP requests and
 * responses. It does not decide what a "turn" is, does not diff anything,
 * and does not know about the Change/AuditRecord model — that logic lives
 * in chunkDiff.ts / claimReconciler.ts / changeModel.ts / revertEngine.ts,
 * all of which are unit-tested without any network involved. Keeping the
 * network edge this thin is what makes the rest of the system testable
 * against plain fixtures instead of a mocked server.
 */

export interface SuperDocsClientOptions {
  apiKey: string;
  baseUrl?: string; // overridable for tests
  fetchImpl?: typeof fetch;
}

export interface SessionSummary {
  session_id: string;
  message_count: number;
  last_activity: string;
}

export interface SessionMessage {
  role: "user" | "assistant";
  content: string;
  turn_index: number;
  checkpoint_id: string | null;
}

export interface SessionHistory {
  messages: SessionMessage[];
  document_state: { html: string; version_id?: string } | null;
}

export interface JobSummary {
  job_id: string;
  status: "pending" | "in_progress" | "awaiting_approval" | "completed" | "failed" | "cancelled";
  created_at?: string;
}

export interface PendingChange {
  change_id: string;
  operation: "edit" | "create" | "delete";
  chunk_id: string | null;
  old_html: string | null;
  new_html: string | null;
  ai_explanation: string;
  insert_after_chunk_id: string | null;
  document_id?: string;
}

export interface JobDetail extends JobSummary {
  metadata?: {
    pending_changes?: PendingChange[];
    awaiting_kind?: "continue_prompt" | string;
  };
  result?: {
    response: string;
    document_changes?: { updated_html?: string };
    usage?: { was_billable: boolean; ops_charged: number };
  };
  error?: string;
}

export class SuperDocsApiError extends Error {
  constructor(
    public readonly status: number,
    public readonly detail: string,
    public readonly retryAfterSeconds: number | null = null
  ) {
    super(`SuperDocs API error ${status}: ${detail}`);
    this.name = "SuperDocsApiError";
  }
}

const DEFAULT_BASE_URL = "https://api.superdocs.app";

export class SuperDocsClient {
  private readonly apiKey: string;
  private readonly baseUrl: string;
  private readonly fetchImpl: typeof fetch;

  constructor(options: SuperDocsClientOptions) {
    this.apiKey = options.apiKey;
    this.baseUrl = options.baseUrl ?? DEFAULT_BASE_URL;
    this.fetchImpl = options.fetchImpl ?? fetch;
  }

  private async request<T>(
    method: "GET" | "POST" | "DELETE" | "PATCH",
    path: string,
    body?: unknown
  ): Promise<T> {
    const init: RequestInit = {
      method,
      headers: {
        Authorization: `Bearer ${this.apiKey}`,
        "Content-Type": "application/json",
      },
    };
    if (body !== undefined) {
      init.body = JSON.stringify(body);
    }
    const response = await this.fetchImpl(`${this.baseUrl}${path}`, init);

    if (!response.ok) {
      let detail = response.statusText;
      try {
        const parsed = (await response.json()) as { detail?: string };
        if (parsed.detail) detail = parsed.detail;
      } catch {
        // Non-JSON error body (e.g. an infrastructure-level 429/502) — keep statusText.
      }
      const retryAfterHeader = response.headers.get("Retry-After");
      throw new SuperDocsApiError(
        response.status,
        detail,
        retryAfterHeader ? Number(retryAfterHeader) : null
      );
    }

    return (await response.json()) as T;
  }

  /** Cheapest way to confirm a key is valid — costs no operations. */
  healthCheckKey(): Promise<{ sessions: SessionSummary[] }> {
    return this.request<{ sessions: SessionSummary[] }>("GET", "/v1/sessions").then((sessions) => ({
      sessions: Array.isArray(sessions) ? sessions : [],
    }));
  }

  listSessions(): Promise<SessionSummary[]> {
    return this.request<SessionSummary[]>("GET", "/v1/sessions");
  }

  getSessionHistory(sessionId: string): Promise<SessionHistory> {
    return this.request<SessionHistory>("GET", `/v1/sessions/${encodeURIComponent(sessionId)}/history`);
  }

  listSessionJobs(sessionId: string): Promise<JobSummary[]> {
    return this.request<JobSummary[]>("GET", `/v1/sessions/${encodeURIComponent(sessionId)}/jobs`);
  }

  getJob(jobId: string): Promise<JobDetail> {
    return this.request<JobDetail>("GET", `/v1/jobs/${encodeURIComponent(jobId)}`);
  }

  approveChange(
    sessionId: string,
    jobId: string,
    decision:
      | { changeId: string; approved: boolean; feedback?: string }
      | { approved: boolean; changes: { change_id: string; approved: boolean }[] }
  ): Promise<JobDetail> {
    const body =
      "changeId" in decision
        ? { job_id: jobId, change_id: decision.changeId, approved: decision.approved, feedback: decision.feedback }
        : { job_id: jobId, approved: decision.approved, changes: decision.changes };
    return this.request<JobDetail>("POST", `/v1/chat/${encodeURIComponent(sessionId)}/approve`, body);
  }

  /** Used only by this extension's own chunk-scoped revert (never SuperDocs's session-level revert — see §3.4/§6.3). */
  editDocument(
    sessionId: string,
    message: string,
    documentHtml?: string
  ): Promise<{ job_id: string; session_id: string }> {
    return this.request("POST", "/v1/chat/async", {
      session_id: sessionId,
      message,
      ...(documentHtml === undefined ? {} : { document_html: documentHtml }),
      approval_mode: "approve_all",
    });
  }
}
