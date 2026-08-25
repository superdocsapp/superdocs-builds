import type {
  ApiReadiness,
  AuditEvent,
  CloseDetail,
  DocumentItem,
  ExportStatus,
  GeneratedArtifact,
  GenerationJob,
  ReviewItem,
  Session,
  SignoffItem,
  SuperDocsLedger,
  Template
} from "./types";

const BASE_URL = (import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000").replace(/\/+$/, "");

export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly blockers: string[];

  constructor(status: number, message: string, code = "", blockers: string[] = []) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
    this.blockers = blockers;
  }
}

/**
 * Plain-English text for every structured error code the API can return.
 *
 * The server sends `{error: "CLOSE_BLOCKED", blockers: [...]}` with no `message`, so
 * without this map the raw code was rendered to the user as the failure text.
 */
const ERROR_MESSAGES: Record<string, string> = {
  CLOSE_BLOCKED: "This period cannot be closed yet.",
  CLOSE_IS_CLOSED: "This period is already closed and can no longer be edited.",
  GENERATION_BLOCKED: "The pack cannot be built yet.",
  GENERATION_IN_PROGRESS: "The pack is already being built. Give it a moment.",
  NOT_GENERATED: "Build the close pack first.",
  NOT_EXPORTED: "Export the pack before downloading it.",
  ALREADY_SIGNED: "That sign-off has already been given.",
  SUPERDOCS_APPROVAL_FAILED: "That change could not be approved. It is still pending, so nothing was lost.",
  SUPERDOCS_EXPORT_FAILED: "The final document could not be produced, so nothing was exported."
};

/** FastAPI returns `detail` as a string, a validation array, or our structured object. */
function readError(status: number, payload: unknown): ApiError {
  const detail = (payload as { detail?: unknown })?.detail ?? payload;

  if (typeof detail === "string") {
    return new ApiError(status, detail);
  }
  if (Array.isArray(detail)) {
    const first = detail[0] as { msg?: string } | undefined;
    return new ApiError(status, first?.msg ?? "Some of the details were not valid.");
  }
  if (detail && typeof detail === "object") {
    const shaped = detail as { error?: string; message?: string; blockers?: string[] };
    const code = shaped.error ?? "";
    return new ApiError(
      status,
      // Prefer our own copy over the server's: the server writes for the record, and a
      // bare code must never be what the user reads.
      ERROR_MESSAGES[code] ?? shaped.message ?? "That did not work. Please try again.",
      code,
      shaped.blockers ?? []
    );
  }
  return new ApiError(status, "That did not work. Please try again.");
}

type RequestOptions = {
  method?: string;
  token?: string;
  json?: unknown;
  body?: BodyInit;
};

/**
 * Clerk session tokens are short-lived - about a minute - and `getToken()` renews them.
 * A token captured once at sign-in would therefore start 401ing partway through a close.
 * When a provider is registered it takes precedence over the token the caller passed, so
 * every request carries a freshly-minted one. Demo mode registers nothing and keeps
 * using the long-lived token threaded through the call sites.
 */
type TokenProvider = (forceRefresh?: boolean) => Promise<string | null>;

let tokenProvider: TokenProvider | null = null;

export function setTokenProvider(provider: TokenProvider | null): void {
  tokenProvider = provider;
}

async function attempt(path: string, options: RequestOptions, forceFreshToken: boolean): Promise<Response> {
  const headers: Record<string, string> = {};

  let token = options.token;
  if (tokenProvider) {
    const minted = await tokenProvider(forceFreshToken);
    // A registered provider returning null means Clerk has no live session to mint from.
    // Falling back to `options.token` here sent the token captured at sign-in, which is
    // long expired by then, so every retry 401d forever while looking like a transient
    // network blip. Fail as the auth error it actually is.
    if (!minted) {
      throw new ApiError(401, "Your session has expired. Please sign in again.", "SESSION_EXPIRED");
    }
    token = minted;
  }

  if (token) headers.Authorization = `Bearer ${token}`;
  if (options.json !== undefined) headers["Content-Type"] = "application/json";

  try {
    return await fetch(`${BASE_URL}${path}`, {
      method: options.method ?? "GET",
      headers,
      body: options.json !== undefined ? JSON.stringify(options.json) : options.body
    });
  } catch {
    throw new ApiError(0, "We cannot reach CloseOrbit right now. Check your connection and try again.");
  }
}

/**
 * One API call, transparently recovering from an expired session token.
 *
 * Clerk session tokens live about a minute and `getToken()` serves a cached copy. That
 * cache goes stale before it renews, which produced long alternating bursts - tens of
 * successes, then tens of 401s - as the same dead token was replayed until Clerk caught
 * up. Retrying once with `skipCache` turns that window into a single extra round trip,
 * so expiry never reaches the caller as an error and never becomes a retry storm.
 *
 * The retry is deliberately once, and only for 401: a second 401 with a freshly minted
 * token is a genuine authentication failure and must be reported as one.
 */
async function request(path: string, options: RequestOptions = {}): Promise<Response> {
  let response = await attempt(path, options, false);

  if (response.status === 401 && tokenProvider) {
    response = await attempt(path, options, true);
  }

  if (!response.ok) {
    let payload: unknown = null;
    try {
      payload = await response.json();
    } catch {
      /* non-JSON error body */
    }
    throw readError(response.status, payload);
  }
  return response;
}

async function json<T>(path: string, options: RequestOptions = {}): Promise<T> {
  return (await request(path, options)).json() as Promise<T>;
}

export const api = {
  startDemoSession: () => json<Session & { expires_in: number }>("/api/v1/auth/demo-session", { method: "POST" }),

  me: (token: string) => json<Session["user"]>("/api/v1/auth/me", { token }),

  listCloses: (token: string) => json<CloseDetail[]>("/api/v1/closes", { token }),

  listTemplates: (token: string) => json<Template[]>("/api/v1/templates", { token }),

  getClose: (token: string, closeId: string) => json<CloseDetail>(`/api/v1/closes/${closeId}`, { token }),

  getReadiness: (token: string, closeId: string) =>
    json<ApiReadiness>(`/api/v1/closes/${closeId}/readiness`, { token }),

  getAudit: (token: string, closeId: string) => json<AuditEvent[]>(`/api/v1/closes/${closeId}/audit`, { token }),

  /** The SuperDocs operation ledger: proof the contract is exercised, not just described. */
  getSuperDocs: (token: string, closeId: string) =>
    json<SuperDocsLedger>(`/api/v1/closes/${closeId}/superdocs`, { token }),

  getArtifacts: (token: string, closeId: string) =>
    json<GeneratedArtifact[]>(`/api/v1/closes/${closeId}/artifacts`, { token }),

  downloadArtifact: async (
    token: string,
    closeId: string,
    artifactId: string,
    filename: string
  ): Promise<{ blob: Blob; filename: string }> => {
    const response = await request(`/api/v1/closes/${closeId}/artifacts/${artifactId}/content`, { token });
    return { blob: await response.blob(), filename };
  },

  uploadDocument: (token: string, closeId: string, file: File) => {
    const form = new FormData();
    form.append("file", file, file.name);
    return json<DocumentItem>(`/api/v1/closes/${closeId}/documents`, { method: "POST", token, body: form });
  },

  deleteDocument: (token: string, closeId: string, documentId: string) =>
    request(`/api/v1/closes/${closeId}/documents/${documentId}`, { token, method: "DELETE" }),

  mapDocument: (token: string, closeId: string, documentId: string, documentType?: string | null) =>
    json<DocumentItem>(`/api/v1/closes/${closeId}/documents/${documentId}/mapping`, {
      method: "PATCH",
      token,
      json: { document_type: documentType ?? null }
    }),

  setChecklistStatus: (token: string, closeId: string, itemId: string, status: "COMPLETE" | "PENDING") =>
    json(`/api/v1/closes/${closeId}/checklist/${itemId}`, { method: "PATCH", token, json: { status } }),

  generate: (token: string, closeId: string) =>
    json<GenerationJob>(`/api/v1/closes/${closeId}/generate`, { method: "POST", token }),

  getJob: (token: string, closeId: string, jobId: string) =>
    json<GenerationJob>(`/api/v1/closes/${closeId}/jobs/${jobId}`, { token }),

  approveReview: (token: string, closeId: string, reviewId: string) =>
    json<ReviewItem>(`/api/v1/closes/${closeId}/reviews/${reviewId}/approve`, { method: "POST", token }),

  rejectReview: (token: string, closeId: string, reviewId: string, reason?: string) =>
    json<ReviewItem>(`/api/v1/closes/${closeId}/reviews/${reviewId}/reject`, {
      method: "POST",
      token,
      json: { reason: reason ?? null }
    }),

  approveSignoff: (token: string, closeId: string, signoffId: string) =>
    json<SignoffItem>(`/api/v1/closes/${closeId}/signoffs/${signoffId}/approve`, { method: "POST", token }),

  getExportStatus: (token: string, closeId: string) =>
    json<ExportStatus>(`/api/v1/closes/${closeId}/export`, { token }),

  createExport: (token: string, closeId: string) =>
    json<{ status: string; filename: string; files: string[] }>(`/api/v1/closes/${closeId}/export`, {
      method: "POST",
      token
    }),

  /** Streams the real zip to the browser. The old export never produced a file. */
  downloadExport: async (token: string, closeId: string): Promise<{ blob: Blob; filename: string }> => {
    const response = await request(`/api/v1/closes/${closeId}/export/download`, { token });
    const disposition = response.headers.get("Content-Disposition") ?? "";
    const match = /filename="?([^"]+)"?/.exec(disposition);
    return { blob: await response.blob(), filename: match?.[1] ?? "close-pack.zip" };
  },

  closePeriod: (token: string, closeId: string) =>
    json<CloseDetail>(`/api/v1/closes/${closeId}/close`, { method: "POST", token })
};

export function saveBlob(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  anchor.rel = "noopener";
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  // Revoking in the same tick as the click cancels the download before the browser has
  // started reading the blob, so nothing ever lands in the downloads folder. The URL has
  // to outlive the click; a timeout is the only reliable signal that it has been picked
  // up, since there is no completion event for an anchor download.
  window.setTimeout(() => URL.revokeObjectURL(url), 60_000);
}

const SESSION_KEY = "closeorbit.session";

export function loadSession(): Session | null {
  try {
    const raw = window.localStorage.getItem(SESSION_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as Session;
    return parsed?.token && parsed?.user ? parsed : null;
  } catch {
    return null;
  }
}

export function storeSession(session: Session | null): void {
  try {
    if (session) window.localStorage.setItem(SESSION_KEY, JSON.stringify(session));
    else window.localStorage.removeItem(SESSION_KEY);
  } catch {
    /* storage unavailable; the session simply will not persist */
  }
}
