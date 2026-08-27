import { z } from 'zod';

import { EXIT_CODES, type ExitCode } from '../core/exit-codes.js';
import { redactUnknown } from '../security/redaction.js';

export interface SafeErrorMetadata {
  readonly httpStatus: number | undefined;
  readonly requestId: string | undefined;
  readonly retryAfter: string | undefined;
  readonly usageLimit: string | undefined;
  readonly usageUsed: string | undefined;
  readonly usageRemaining: string | undefined;
  readonly details: unknown;
  readonly retryable?: boolean;
  readonly retryAfterSeconds?: number | null;
  readonly attemptCount?: number;
  readonly retryKind?: 'application-429' | 'infrastructure-429' | 'transient' | 'none';
  readonly remoteState?: 'known-rejected' | 'unknown' | 'known';
  readonly operationId?: string;
}

export class SdxError extends Error {
  public readonly exitCode: ExitCode;
  public readonly metadata: SafeErrorMetadata | undefined;

  public constructor(
    message: string,
    exitCode: ExitCode,
    metadata?: SafeErrorMetadata,
    options?: ErrorOptions,
  ) {
    super(message, options);
    this.name = 'SdxError';
    this.exitCode = exitCode;
    this.metadata = metadata;
  }
}

export function schemaMismatch(
  operation: string,
  issue: z.ZodError | Error,
): SdxError {
  const details =
    issue instanceof z.ZodError
      ? issue.issues.map(({ code, path, message }) => ({ code, path, message }))
      : issue.message;
  return new SdxError(
    `SuperDocs returned an unexpected ${operation} response.`,
    EXIT_CODES.schemaMismatch,
    {
      httpStatus: undefined,
      requestId: undefined,
      retryAfter: undefined,
      usageLimit: undefined,
      usageUsed: undefined,
      usageRemaining: undefined,
      details: redactUnknown(details),
    },
    { cause: issue },
  );
}

export function asSdxError(
  error: unknown,
  fallbackMessage: string,
  fallbackCode: ExitCode,
): SdxError {
  if (error instanceof SdxError) {
    return error;
  }
  if (error instanceof Error && error.name === 'AbortError') {
    return new SdxError('Operation interrupted by the user.', EXIT_CODES.interrupted);
  }
  return new SdxError(fallbackMessage, fallbackCode, undefined, {
    cause: error,
  });
}
