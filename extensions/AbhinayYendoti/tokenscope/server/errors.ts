/**
 * Errors the task pane can render as something a person can act on.
 *
 * Every failure that reaches the UI is one of these. A raw stack trace or an
 * upstream HTML error page never gets forwarded: the code drives which state the
 * pane shows, the message and hint are what the reader is told.
 */
export type ErrorCode =
  | "no_api_key"
  | "auth_failed"
  | "quota_exhausted"
  | "invalid_selection"
  | "empty_instruction"
  | "upstream_error"
  | "timeout"
  | "unexpected_response"
  | "job_failed";

export class TokenScopeError extends Error {
  override readonly name = "TokenScopeError";
  readonly code: ErrorCode;
  readonly status: number;
  readonly hint: string | undefined;

  constructor(code: ErrorCode, message: string, options: { status?: number; hint?: string } = {}) {
    super(message);
    this.code = code;
    this.status = options.status ?? STATUS[code];
    this.hint = options.hint;
  }
}

const STATUS: Record<ErrorCode, number> = {
  no_api_key: 503,
  auth_failed: 502,
  quota_exhausted: 429,
  invalid_selection: 400,
  empty_instruction: 400,
  upstream_error: 502,
  timeout: 504,
  unexpected_response: 502,
  job_failed: 502
};

/** Anything thrown anywhere, reduced to something the pane can show. */
export function toErrorBody(error: unknown): {
  status: number;
  body: { error: { code: ErrorCode; message: string; hint?: string } };
} {
  if (error instanceof TokenScopeError) {
    return {
      status: error.status,
      body: {
        error: {
          code: error.code,
          message: error.message,
          ...(error.hint === undefined ? {} : { hint: error.hint })
        }
      }
    };
  }

  const message = error instanceof Error ? error.message : String(error);

  return {
    status: 500,
    body: {
      error: {
        code: "upstream_error",
        message: `TokenScope failed unexpectedly: ${message}`,
        hint: "Check the server log for the full error."
      }
    }
  };
}
