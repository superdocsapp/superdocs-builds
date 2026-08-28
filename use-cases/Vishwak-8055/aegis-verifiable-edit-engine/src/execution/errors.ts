import { redact } from '../evidence/redact.js';

export class SuperDocError extends Error {
  override name: string = 'SuperDocError';
  readonly code: string;
  readonly correlationId: string;
  /** Distinct from the built-in `Error.cause` (ES2022) to avoid ambiguity about which one carries the wrapped SDK error. */
  readonly sourceError?: unknown;

  constructor(message: string, code: string, correlationId: string, sourceError?: unknown) {
    super(message);
    this.name = 'SuperDocError';
    this.code = code;
    this.correlationId = correlationId;
    this.sourceError = sourceError;
  }

  /** Safe to show a user or embed in an EditProof: no stack trace, no cause payload. */
  toUserSafeMessage(): string {
    return `SuperDoc operation failed (${this.code}, correlation ${this.correlationId}). See server logs for detail.`;
  }

  /** Safe to log: redacted, and deliberately excludes the raw `cause`, which may wrap an SDK error containing request payloads. */
  toLogPayload(): Record<string, unknown> {
    return redact({ code: this.code, correlationId: this.correlationId, message: this.message });
  }
}

export class SuperDocTimeoutError extends SuperDocError {
  constructor(correlationId: string, timeoutMs: number) {
    super(`SuperDoc operation exceeded the ${timeoutMs}ms timeout`, 'TIMEOUT', correlationId);
    this.name = 'SuperDocTimeoutError';
  }
}

export class SuperDocUnavailableError extends SuperDocError {
  constructor(correlationId: string, cause?: unknown) {
    super('SuperDoc host is unavailable', 'UNAVAILABLE', correlationId, cause);
    this.name = 'SuperDocUnavailableError';
  }
}
