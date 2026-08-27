import type {
  AccountStatus,
  ApiErrorBody,
  DocumentSnapshot,
  JobWork,
  Measurement,
  ProposedChange,
  WholeDocumentRun
} from "../shared/types.js";

/**
 * The pane's view of the TokenScope server.
 *
 * The SuperDocs key lives on the server; this file only knows about
 * `/api`. Every failure arrives as a typed body, so the pane never has to
 * render an exception.
 */

export class ApiError extends Error {
  override readonly name = "ApiError";
  readonly code: string;
  readonly hint: string | undefined;

  constructor(code: string, message: string, hint?: string) {
    super(message);
    this.code = code;
    this.hint = hint;
  }
}

export interface ScopeReport {
  inScope: ProposedChange[];
  outOfScope: ProposedChange[];
}

export interface RewriteResponse {
  sessionId: string;
  jobId: string;
  reply: string;
  changes: ProposedChange[];
  scope: ScopeReport;
  measurement: Measurement;
  work: JobWork;
  elapsedMs: number;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;

  try {
    response = await fetch(`/api${path}`, init);
  } catch {
    throw new ApiError(
      "server_unreachable",
      "The TokenScope server is not responding.",
      "Start it with `npm run server`, or `npm run dev` to run both halves."
    );
  }

  const text = await response.text();
  let body: unknown;

  try {
    body = JSON.parse(text);
  } catch {
    throw new ApiError(
      "unexpected_response",
      `The TokenScope server returned a non-JSON body (HTTP ${response.status}).`,
      text.slice(0, 160)
    );
  }

  if (!response.ok) {
    const error = (body as ApiErrorBody).error;

    throw new ApiError(
      error?.code ?? "unexpected_response",
      error?.message ?? `The request failed with HTTP ${response.status}.`,
      error?.hint
    );
  }

  return body as T;
}

function post<T>(path: string, json: unknown): Promise<T> {
  return request<T>(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(json)
  });
}

export function getStatus(): Promise<AccountStatus> {
  return request<AccountStatus>("/status");
}

export function rewrite(input: {
  document: DocumentSnapshot;
  selectedText: string;
  instruction: string;
}): Promise<RewriteResponse> {
  return post<RewriteResponse>("/rewrite", input);
}

export interface WholeDocumentResponse {
  run: WholeDocumentRun;
  /** The whole comparison, recomputed on the server with the measured value in it. */
  measurement: Measurement;
}

export function measureWholeDocument(input: {
  document: DocumentSnapshot;
  selectedText: string;
  instruction: string;
  surgical: { work: JobWork; reportedTokens: number | null };
}): Promise<WholeDocumentResponse> {
  return post<WholeDocumentResponse>("/whole-document", input);
}

export function applyChange(input: {
  sessionId: string;
  jobId: string;
  changeId: string;
}): Promise<{ applied: true }> {
  return post<{ applied: true }>("/apply", input);
}
