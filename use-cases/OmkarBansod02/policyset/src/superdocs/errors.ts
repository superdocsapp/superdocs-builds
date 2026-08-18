export class SuperDocsError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "SuperDocsError";
  }
}

export class SuperDocsInvalidResponse extends SuperDocsError {
  constructor(message: string) {
    super(message);
    this.name = "SuperDocsInvalidResponse";
  }
}

/**
 * Structured diagnostics for one failed SuperDocs request. Kept deliberately
 * narrow: only a machine-readable provider code and a short, redacted,
 * length-bounded detail string are retained. Raw response bodies, arbitrary
 * HTML, and request headers are never captured here.
 */
export type SuperDocsErrorDiagnostics = {
  statusCode: number | null;
  requestId: string | null;
  providerCode: string | null;
  providerDetail: string | null;
  outcomeUnknown: boolean;
};

/** Upper bound on a retained provider detail string. */
export const PROVIDER_DETAIL_MAX_LENGTH = 300;

export class SuperDocsRequestError extends SuperDocsError {
  readonly statusCode: number | null;
  readonly requestId: string | null;
  readonly outcomeUnknown: boolean;
  /** Machine-readable provider error code, when the body carried one. */
  readonly providerCode: string | null;
  /** Short, redacted, bounded provider message. Never a raw body. */
  readonly providerDetail: string | null;

  constructor(
    message: string,
    options: {
      statusCode?: number | null;
      requestId?: string | null;
      outcomeUnknown?: boolean;
      providerCode?: string | null;
      providerDetail?: string | null;
    } = {},
  ) {
    super(message);
    this.name = "SuperDocsRequestError";
    this.statusCode = options.statusCode ?? null;
    this.requestId = options.requestId ?? null;
    this.outcomeUnknown = options.outcomeUnknown ?? false;
    this.providerCode = sanitizeProviderField(options.providerCode);
    this.providerDetail = sanitizeProviderField(options.providerDetail);
  }

  /**
   * The friendly `message` stays user-facing. Internal callers (live
   * validation tooling, evidence capture) use this to record what SuperDocs
   * actually said.
   */
  diagnostics(): SuperDocsErrorDiagnostics {
    return {
      statusCode: this.statusCode,
      requestId: this.requestId,
      providerCode: this.providerCode,
      providerDetail: this.providerDetail,
      outcomeUnknown: this.outcomeUnknown,
    };
  }
}

function sanitizeProviderField(value: string | null | undefined): string | null {
  if (typeof value !== "string") {
    return null;
  }
  const collapsed = value.replace(/\s+/g, " ").trim();
  if (!collapsed) {
    return null;
  }
  const redacted = redactSecrets(collapsed);
  return redacted.length > PROVIDER_DETAIL_MAX_LENGTH
    ? `${redacted.slice(0, PROVIDER_DETAIL_MAX_LENGTH)}…`
    : redacted;
}

/**
 * Shared redaction for anything that may be written to disk or a report.
 * Defined here (the dependency-free module) so error diagnostics and proposal
 * evidence cannot drift apart.
 */
export function redactSecrets(value: string): string {
  return value
    .replace(/\b(?:sk_|sk-)[a-z0-9_-]{8,}\b/gi, "[REDACTED_SECRET]")
    .replace(/(bearer\s+)[a-z0-9._~+/-]+=*/gi, "$1[REDACTED]")
    .replace(
      /((?:api[_ -]?key|authorization)\s*[:=]\s*)[^\s<"']+/gi,
      "$1[REDACTED]",
    );
}
