import { createHash, randomUUID } from "node:crypto";

import { SuperDocsInvalidResponse, SuperDocsRequestError } from "./errors";
import {
  DOCX_MIME,
  PDF_MIME,
  SUPERDOCS_API_BASE,
  SUPERDOCS_JOB_STATUSES,
  SUPERDOCS_OPEN_MODES,
  type ExportArtifact,
  type ExportFormat,
  type FocusedDocument,
  type IngestedDocument,
  type JobReference,
  type JobSnapshot,
  type PendingChange,
  type ProposalOperation,
  type ReviewDecision,
  type ReviewReceipt,
  type SessionDocument,
  type SessionDocumentIdentity,
  type StartChatInput,
  type SuperDocsClientOptions,
  type SuperDocsJobStatus,
  type SuperDocsOpenMode,
} from "./types";

const SESSION_PATTERN = /^[a-zA-Z0-9_.-]+$/;
const SAFE_REQUEST_ID_PATTERN = /^[A-Za-z0-9_.:-]{1,128}$/;
const PROPOSAL_OPERATION_SET = new Set<string>(["edit", "create", "delete"]);

export function createSessionId(): string {
  return `policyset-${randomUUID()}`;
}

export function buildStartChatPayload(input: StartChatInput): Record<string, string> {
  requireSessionId(input.sessionId);
  if (!input.message.trim()) {
    throw new Error("edit instruction must not be empty");
  }

  const payload: Record<string, string> = {
    message: input.message,
    session_id: input.sessionId,
    approval_mode: "ask_every_time",
    response_mode: "full",
  };

  if (input.documentId !== undefined) {
    if (!input.documentId) {
      throw new Error("document_id must be non-empty when provided");
    }
    payload.document_id = input.documentId;
  }

  return payload;
}

export class SuperDocsClient {
  private readonly apiKey: string;
  private readonly apiBase: string;
  private readonly fetchImpl: typeof fetch;

  constructor(options: SuperDocsClientOptions) {
    if (!options.apiKey.trim()) {
      throw new Error("SUPERDOCS_API_KEY is not configured");
    }
    this.apiKey = options.apiKey;
    this.apiBase = (options.apiBase ?? SUPERDOCS_API_BASE).replace(/\/$/, "");
    this.fetchImpl = options.fetch ?? fetch;
  }

  async uploadDocx(input: {
    sessionId: string;
    filename: string;
    bytes: Uint8Array;
    openMode: SuperDocsOpenMode;
  }): Promise<IngestedDocument> {
    requireSessionId(input.sessionId);
    requireFilename(input.filename);
    if (input.bytes.byteLength === 0) {
      throw new Error("DOCX upload bytes must not be empty");
    }
    if (!isOpenMode(input.openMode)) {
      throw new Error("unsupported SuperDocs open_mode");
    }

    const form = new FormData();
    form.append(
      "file",
      new File([Buffer.from(input.bytes)], input.filename, { type: DOCX_MIME }),
    );
    form.append("session_id", input.sessionId);
    form.append("open_mode", input.openMode);

    const response = await this.request("POST", "/documents/upload", {
      body: form,
      outcomeSensitive: true,
    });
    const payload = jsonObject(response);

    const returnedSession = requiredString(payload, "session_id");
    if (returnedSession !== input.sessionId) {
      throw new SuperDocsInvalidResponse(
        "SuperDocs upload returned an unexpected session",
      );
    }

    return {
      identity: {
        sessionId: input.sessionId,
        documentId: requiredString(payload, "document_id"),
      },
      versionId: requiredString(payload, "version_id"),
      filename: optionalString(payload.filename),
      chunksCount: optionalNonNegativeInt(payload.chunks_count, "chunks_count"),
    };
  }

  /**
   * Authoritative multi-document state. Do not treat upload's embedded
   * roster as complete.
   */
  async listSessionDocuments(
    sessionId: string,
    options: { includeHtml: boolean },
  ): Promise<readonly SessionDocument[]> {
    requireSessionId(sessionId);
    const response = await this.request(
      "GET",
      `/sessions/${encodeURIComponent(sessionId)}/documents?include_html=${options.includeHtml}`,
    );
    const payload = jsonValue(response);
    const values = Array.isArray(payload)
      ? payload
      : isRecord(payload)
        ? payload.documents
        : undefined;
    if (!Array.isArray(values)) {
      throw new SuperDocsInvalidResponse("SuperDocs document roster was not a list");
    }

    return values.map((value) => {
      if (!isRecord(value)) {
        throw new SuperDocsInvalidResponse(
          "SuperDocs document roster contained an invalid item",
        );
      }
      const html = value.html;
      if (html != null && typeof html !== "string") {
        throw new SuperDocsInvalidResponse("SuperDocs roster HTML had an invalid shape");
      }
      const chunksValue = value.chunks_count ?? value.sections_count;
      return {
        identity: {
          sessionId,
          documentId: requiredString(value, "document_id"),
          durableDocumentId: optionalString(value.durable_document_id) ?? undefined,
        },
        title: optionalString(value.title),
        focused: Boolean(value.focused),
        versionId: optionalString(value.version_id),
        chunksCount:
          chunksValue == null
            ? null
            : requireNonNegativeInt(chunksValue, "chunks_count"),
        html: typeof html === "string" ? html : null,
      };
    });
  }

  async focusDocument(
    identity: SessionDocumentIdentity,
  ): Promise<FocusedDocument> {
    requireSessionId(identity.sessionId);
    if (!identity.documentId) {
      throw new Error("focus requires a document_id");
    }

    const response = await this.request(
      "POST",
      `/sessions/${encodeURIComponent(identity.sessionId)}/documents/${encodeURIComponent(identity.documentId)}/focus?include_html=false`,
      { outcomeSensitive: true },
    );
    let payload: JsonRecord = jsonObject(response);
    if (isRecord(payload.document)) {
      payload = payload.document;
    }

    const returnedId = optionalString(
      payload.document_id ?? payload.focused_document_id,
    );
    if (!returnedId) {
      throw new SuperDocsInvalidResponse(
        "SuperDocs focus response omitted the target identity",
      );
    }
    if (returnedId !== identity.documentId) {
      throw new SuperDocsInvalidResponse("SuperDocs focused an unexpected document");
    }
    if (payload.focused === false) {
      throw new SuperDocsInvalidResponse(
        "SuperDocs did not confirm that the requested document is focused",
      );
    }

    const durableId = optionalString(payload.durable_document_id);
    if (
      identity.durableDocumentId &&
      durableId &&
      durableId !== identity.durableDocumentId
    ) {
      throw new SuperDocsInvalidResponse(
        "SuperDocs focus returned an unexpected durable identity",
      );
    }

    return {
      identity: {
        sessionId: identity.sessionId,
        documentId: identity.documentId,
        durableDocumentId: durableId ?? identity.durableDocumentId,
      },
      focused: payload.focused === undefined ? true : Boolean(payload.focused),
      versionId: optionalString(payload.version_id),
    };
  }

  async startChat(input: StartChatInput): Promise<JobReference> {
    const payload = buildStartChatPayload(input);
    const response = await this.request("POST", "/chat/async", {
      json: payload,
      outcomeSensitive: true,
    });
    return parseJobReference(jsonObject(response), input.sessionId);
  }

  async getJob(jobId: string): Promise<JobSnapshot> {
    if (!jobId) {
      throw new Error("job_id must not be empty");
    }
    const response = await this.request(
      "GET",
      `/jobs/${encodeURIComponent(jobId)}`,
    );
    return parseJobSnapshot(jsonObject(response));
  }

  async submitReview(input: {
    sessionId: string;
    jobId: string;
    decisions: readonly ReviewDecision[];
  }): Promise<ReviewReceipt> {
    requireSessionId(input.sessionId);
    if (input.decisions.length === 0) {
      throw new Error("at least one explicit review decision is required");
    }
    const changeIds = input.decisions.map((decision) => decision.changeId);
    if (new Set(changeIds).size !== changeIds.length) {
      throw new Error("review decisions contain duplicate change IDs");
    }

    const response = await this.request(
      "POST",
      `/chat/${encodeURIComponent(input.sessionId)}/approve`,
      {
        json: {
          job_id: input.jobId,
          approved: true,
          changes: input.decisions.map((decision) => {
            const item: Record<string, string | boolean> = {
              change_id: decision.changeId,
              approved: decision.approved,
            };
            if (decision.feedback !== undefined) {
              item.feedback = decision.feedback;
            }
            return item;
          }),
        },
        outcomeSensitive: true,
      },
    );
    const payload = jsonObject(response);
    return {
      status: requiredString(payload, "status"),
      batchComplete: Boolean(payload.batch_complete),
    };
  }

  /**
   * Export is focus-scoped. This is the only export entry point: it always
   * focuses the target and verifies the returned identity before exporting.
   */
  async exportFocusedDocument(
    identity: SessionDocumentIdentity,
    options: { format: ExportFormat; filename: string },
  ): Promise<ExportArtifact> {
    requireSessionId(identity.sessionId);
    requireFilename(options.filename);
    if (options.format !== "docx" && options.format !== "pdf") {
      throw new Error("unsupported export format");
    }

    await this.focusDocument(identity);

    const response = await this.request("POST", "/documents/export", {
      json: {
        session_id: identity.sessionId,
        format: options.format,
        options: { filename: options.filename, fidelity: "strict" },
      },
    });

    const expectedType = options.format === "docx" ? DOCX_MIME : PDF_MIME;
    const contentType = (response.contentType ?? "").split(";", 1)[0].trim();
    if (contentType !== expectedType || response.body.byteLength === 0) {
      throw new SuperDocsInvalidResponse(
        `SuperDocs export did not return a non-empty ${options.format.toUpperCase()}`,
      );
    }

    return {
      format: options.format,
      bytes: response.body,
      contentType,
      sha256: sha256Hex(response.body),
      sizeBytes: response.body.byteLength,
      contentDisposition: response.headers.get("Content-Disposition"),
      warnings: decodeExportWarnings(response.headers.get("X-Export-Warnings")),
    };
  }

  private async request(
    method: string,
    path: string,
    options: {
      json?: unknown;
      body?: BodyInit;
      outcomeSensitive?: boolean;
    } = {},
  ): Promise<AdapterResponse> {
    const headers = new Headers({
      Authorization: `Bearer ${this.apiKey}`,
    });
    let body: BodyInit | undefined = options.body;
    if (options.json !== undefined) {
      headers.set("Content-Type", "application/json");
      body = JSON.stringify(options.json);
    }

    let response: Response;
    try {
      response = await this.fetchImpl(`${this.apiBase}${path}`, {
        method,
        headers,
        body,
      });
    } catch {
      throw new SuperDocsRequestError("SuperDocs is unavailable", {
        outcomeUnknown: options.outcomeSensitive === true,
      });
    }

    const bytes = new Uint8Array(await response.arrayBuffer());
    if (!response.ok) {
      throw statusError(
        response.status,
        requestId(response),
        options.outcomeSensitive === true,
        providerErrorFields(bytes, response.headers.get("Content-Type")),
      );
    }

    return {
      headers: response.headers,
      contentType: response.headers.get("Content-Type"),
      body: bytes,
    };
  }
}

type JsonRecord = Record<string, unknown>;

type AdapterResponse = {
  headers: Headers;
  contentType: string | null;
  body: Uint8Array;
};

function parseJobReference(
  payload: JsonRecord,
  expectedSessionId?: string,
): JobReference {
  const status = requiredString(payload, "status");
  if (!isJobStatus(status)) {
    throw new SuperDocsInvalidResponse("SuperDocs returned an unknown job state");
  }
  const reference: JobReference = {
    jobId: requiredString(payload, "job_id"),
    sessionId: requiredString(payload, "session_id"),
    status,
  };
  if (expectedSessionId && reference.sessionId !== expectedSessionId) {
    throw new SuperDocsInvalidResponse("SuperDocs returned a job from another session");
  }
  return reference;
}

function parseJobSnapshot(payload: JsonRecord): JobSnapshot {
  const metadataValue = payload.metadata;
  const metadata = metadataValue == null ? {} : metadataValue;
  if (!isRecord(metadata)) {
    throw new SuperDocsInvalidResponse("SuperDocs job metadata had an invalid shape");
  }

  // pending_changes may be null while in_progress. That is not a review batch.
  const pendingValue = metadata.pending_changes;
  const pendingList = pendingValue == null ? [] : pendingValue;
  if (!Array.isArray(pendingList)) {
    throw new SuperDocsInvalidResponse("SuperDocs pending_changes was not a list");
  }

  const errorValue = payload.error;
  const errorCode = isRecord(errorValue)
    ? optionalString(errorValue.code ?? errorValue.type)
    : null;

  return {
    reference: parseJobReference(payload),
    progress:
      payload.progress == null
        ? null
        : requireNonNegativeInt(payload.progress, "progress"),
    awaitingKind: optionalString(metadata.awaiting_kind),
    pendingChanges: pendingList.map(parsePendingChange),
    errorCode,
  };
}

function parsePendingChange(value: unknown): PendingChange {
  if (!isRecord(value)) {
    throw new SuperDocsInvalidResponse("SuperDocs pending change had an invalid shape");
  }
  const operation = requiredString(value, "operation");
  if (!PROPOSAL_OPERATION_SET.has(operation)) {
    throw new SuperDocsInvalidResponse("SuperDocs pending change had an invalid shape");
  }
  return {
    changeId: requiredString(value, "change_id"),
    operation: operation as ProposalOperation,
    documentId:
      typeof value.document_id === "string" ? value.document_id : "",
    chunkId: optionalString(value.chunk_id, { allowEmpty: true }),
    oldHtml: optionalString(value.old_html, { allowEmpty: true }),
    newHtml: optionalString(value.new_html, { allowEmpty: true }),
    aiExplanation: optionalString(value.ai_explanation, { allowEmpty: true }),
  };
}

function decodeExportWarnings(raw: string | null): Record<string, unknown>[] {
  if (raw == null || raw === "") {
    return [];
  }
  try {
    const decoded = Buffer.from(raw, "base64").toString("utf8");
    const payload: unknown = JSON.parse(decoded);
    if (!Array.isArray(payload) || payload.some((item) => !isRecord(item))) {
      throw new Error("invalid warnings");
    }
    return payload as Record<string, unknown>[];
  } catch {
    throw new SuperDocsInvalidResponse("SuperDocs export warnings could not be decoded");
  }
}

function jsonValue(response: AdapterResponse): unknown {
  try {
    return JSON.parse(new TextDecoder().decode(response.body)) as unknown;
  } catch {
    throw new SuperDocsInvalidResponse("SuperDocs returned invalid JSON");
  }
}

function jsonObject(response: AdapterResponse): JsonRecord {
  const payload = jsonValue(response);
  if (!isRecord(payload)) {
    throw new SuperDocsInvalidResponse("SuperDocs returned an invalid response shape");
  }
  return payload;
}

function requiredString(payload: JsonRecord, key: string): string {
  const value = payload[key];
  if (typeof value !== "string" || !value) {
    throw new SuperDocsInvalidResponse(`SuperDocs response omitted required ${key}`);
  }
  return value;
}

function optionalString(
  value: unknown,
  options: { allowEmpty?: boolean } = {},
): string | null {
  if (value == null) {
    return null;
  }
  if (typeof value !== "string" || (!options.allowEmpty && !value)) {
    throw new SuperDocsInvalidResponse("SuperDocs response contained an invalid string field");
  }
  return value;
}

function optionalNonNegativeInt(value: unknown, label: string): number | null {
  if (value == null) {
    return null;
  }
  return requireNonNegativeInt(value, label);
}

function requireNonNegativeInt(value: unknown, label: string): number {
  if (typeof value !== "number" || !Number.isInteger(value) || value < 0) {
    throw new SuperDocsInvalidResponse(`SuperDocs ${label} was not a non-negative integer`);
  }
  return value;
}

function requireSessionId(sessionId: string): void {
  if (sessionId.length > 256 || SESSION_PATTERN.exec(sessionId) === null) {
    throw new Error("session_id is not valid for SuperDocs");
  }
}

function requireFilename(filename: string): void {
  if (!filename || filename !== filename.trim() || filename.includes("/") || filename.includes("\\")) {
    throw new Error("filename must be a non-empty basename");
  }
}

function isOpenMode(value: string): value is SuperDocsOpenMode {
  return (SUPERDOCS_OPEN_MODES as readonly string[]).includes(value);
}

function isJobStatus(value: string): value is SuperDocsJobStatus {
  return (SUPERDOCS_JOB_STATUSES as readonly string[]).includes(value);
}

function isRecord(value: unknown): value is JsonRecord {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function requestId(response: Response): string | null {
  const value = response.headers.get("X-Request-ID") ?? response.headers.get("Request-ID");
  if (value == null || SAFE_REQUEST_ID_PATTERN.exec(value) === null) {
    return null;
  }
  return value;
}

/**
 * Extracts only a machine-readable code and a short human message from a
 * JSON error body. A non-JSON body (an HTML error page, for example) yields
 * nothing — we never retain arbitrary response content. `SuperDocsRequestError`
 * redacts and length-bounds whatever is returned here.
 */
function providerErrorFields(
  bytes: Uint8Array,
  contentType: string | null,
): { code: string | null; detail: string | null } {
  const empty = { code: null, detail: null };
  const mediaType = (contentType ?? "").split(";", 1)[0].trim().toLowerCase();
  if (!mediaType.includes("json") || bytes.byteLength === 0) {
    return empty;
  }

  let payload: unknown;
  try {
    payload = JSON.parse(new TextDecoder().decode(bytes)) as unknown;
  } catch {
    return empty;
  }
  if (!isRecord(payload)) {
    return empty;
  }

  // FastAPI-style bodies nest the real payload under `error` or `detail`.
  const nested = isRecord(payload.error)
    ? payload.error
    : isRecord(payload.detail)
      ? payload.detail
      : payload;

  return {
    code: firstStringField(nested, ["code", "error_code", "type"]),
    detail: firstStringField(nested, ["detail", "message", "error", "title"]),
  };
}

function firstStringField(
  payload: JsonRecord,
  keys: readonly string[],
): string | null {
  for (const key of keys) {
    const value = payload[key];
    if (typeof value === "string" && value.trim()) {
      return value;
    }
  }
  return null;
}

function statusError(
  status: number,
  requestIdValue: string | null,
  outcomeSensitive: boolean,
  provider: { code: string | null; detail: string | null } = {
    code: null,
    detail: null,
  },
): SuperDocsRequestError {
  let message = "SuperDocs rejected the request";
  if (status === 401 || status === 403) {
    message = "SuperDocs rejected the configured server credential";
  } else if (status === 404) {
    message = "SuperDocs resource was not found";
  } else if (status === 409) {
    message = "SuperDocs rejected the operation for the current job state";
  } else if (status === 429) {
    message = "SuperDocs rate limit was reached";
  } else if (status >= 500) {
    message = "SuperDocs is unavailable";
  }
  return new SuperDocsRequestError(message, {
    statusCode: status,
    requestId: requestIdValue,
    outcomeUnknown: outcomeSensitive && status >= 500,
    providerCode: provider.code,
    providerDetail: provider.detail,
  });
}

function sha256Hex(value: Uint8Array): string {
  return createHash("sha256").update(value).digest("hex");
}
