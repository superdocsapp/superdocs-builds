/**
 * One error shape for the whole API.
 *
 * The browser gets { error: { code, message, detail, requestId, retryable } }
 * for every failure, so the UI can decide what to say and whether a retry is
 * worth offering without string-matching messages.
 */

export class AppError extends Error {
  constructor(code, message, { status = 400, detail, retryable = false, data } = {}) {
    super(message);
    this.name = "AppError";
    this.code = code;
    this.status = status;
    this.detail = detail;
    this.retryable = retryable;
    this.data = data;
  }
}

export const errors = {
  notFound: (message, detail) => new AppError("not_found", message, { status: 404, detail }),
  invalid: (message, data) => new AppError("invalid_request", message, { status: 422, data }),
  conflict: (message, data) => new AppError("conflict", message, { status: 409, data }),
  gone: (message) =>
    new AppError("session_expired", message, {
      status: 410,
      detail: "Document sessions are kept for a limited time. Start the run again."
    }),
  quota: (message, data) =>
    new AppError("quota_exhausted", message, { status: 429, data, retryable: false }),
  rateLimited: (message) =>
    new AppError("rate_limited", message, { status: 429, retryable: true }),
  upstream: (message, detail, data) =>
    new AppError("upstream_failure", message, { status: 502, detail, retryable: true, data })
};

export function toEnvelope(error, requestId) {
  if (error instanceof AppError) {
    return {
      status: error.status,
      body: {
        error: {
          code: error.code,
          message: error.message,
          detail: error.detail ?? null,
          retryable: error.retryable,
          requestId,
          ...(error.data ? { data: error.data } : {})
        }
      }
    };
  }

  return {
    status: 500,
    body: {
      error: {
        code: "internal_error",
        message: "The request failed.",
        detail: String(error?.message ?? error),
        retryable: true,
        requestId
      }
    }
  };
}
