export interface AsyncEditOptions {
  readonly modelTier?: 'core' | 'turbo' | 'pro' | 'max';
  readonly documentId?: string;
}

import { createReadStream, createWriteStream } from 'node:fs';
import { link, readdir, rename, stat, unlink } from 'node:fs/promises';
import { basename, dirname, join } from 'node:path';
import { randomUUID } from 'node:crypto';
import { Readable } from 'node:stream';
import { pipeline } from 'node:stream/promises';

import type { z } from 'zod';

import { EXIT_CODES, type ExitCode } from '../core/exit-codes.js';
import { redactText, redactUnknown, redactUrl } from '../security/redaction.js';
import { SdxError, asSdxError, schemaMismatch } from './errors.js';
import { RetryPolicy, type RetryPlan, type RetryPolicyOptions, type RetrySafety } from './retry.js';
import {
  ApiErrorBodySchema,
  ApprovalResponseSchema,
  AsyncChatResponseSchema,
  ContinueResponseSchema,
  DownloadUrlResponseSchema,
  JobResponseSchema,
  ProcessDocumentResponseSchema,
  UploadUrlResponseSchema,
  type ApiJob,
  type AsyncChatResponse,
  type DownloadUrlResponse,
  type ExportFormat,
  type ProcessDocumentResponse,
  type UploadUrlResponse,
} from './schemas.js';

export interface ApprovalDecision {
  readonly change_id: string;
  readonly approved: boolean;
  readonly feedback?: string;
}

export interface ClientUsage {
  readonly apiCalls: number;
  readonly uploadedBytes: number;
  readonly downloadedBytes: number;
}

export interface DownloadResult {
  readonly bytes: number;
  readonly warnings: readonly string[];
}

interface RequestOptions {
  readonly method: string;
  readonly body: unknown | undefined;
  readonly signal: AbortSignal | undefined;
}

type FetchImplementation = typeof fetch;

export interface ClientRetryOptions extends RetryPolicyOptions {
  readonly retryBudgetMs?: number;
  readonly onRetry?: (plan: RetryPlan, operation: string) => void;
}

interface AttemptedResponse {
  readonly response: Response;
  readonly attempt: number;
  readonly plan: RetryPlan;
}

function processIsAlive(pid: number): boolean {
  try { process.kill(pid, 0); return true; }
  catch (error) { return (error as NodeJS.ErrnoException).code !== 'ESRCH'; }
}

async function cleanupDeadDownloadTemporaries(destination: string): Promise<void> {
  const directory = dirname(destination); const prefix = `.${basename(destination)}.`;
  let names: string[];
  try { names = await readdir(directory); }
  catch { return; }
  await Promise.all(names.map(async (name) => {
    if (!name.startsWith(prefix) || !name.endsWith('.tmp')) return;
    const ownerText = name.slice(prefix.length).split('.', 1)[0];
    const ownerPid = Number(ownerText);
    if (!Number.isSafeInteger(ownerPid) || ownerPid <= 0 || processIsAlive(ownerPid)) return;
    await unlink(join(directory, name)).catch(() => undefined);
  }));
}

export const SUPERDOCS_API_BASE_URL = 'https://api.superdocs.app';

export class SuperDocsClient {
  private apiCallCount = 0;
  private uploadByteCount = 0;
  private downloadByteCount = 0;
  private readonly retryPolicy: RetryPolicy;
  private readonly retryBudgetMs: number;
  private readonly onRetry: ((plan: RetryPlan, operation: string) => void) | undefined;

  public constructor(
    private readonly apiKey: string,
    private readonly baseUrl = new URL(SUPERDOCS_API_BASE_URL),
    private readonly fetchImplementation: FetchImplementation = fetch,
    retryOptions: ClientRetryOptions = {},
  ) {
    this.retryPolicy = new RetryPolicy(retryOptions);
    this.retryBudgetMs = retryOptions.retryBudgetMs ?? 300_000;
    this.onRetry = retryOptions.onRetry;
  }

  public get usage(): ClientUsage {
    return {
      apiCalls: this.apiCallCount,
      uploadedBytes: this.uploadByteCount,
      downloadedBytes: this.downloadByteCount,
    };
  }

  public requestUploadUrl(
    filename: string,
    contentType: string,
    sizeBytes: number,
    signal?: AbortSignal,
  ): Promise<UploadUrlResponse> {
    return this.apiJson(
      '/v1/uploads',
      {
        method: 'POST',
        body: {
          filename,
          content_type: contentType,
          size_bytes: sizeBytes,
          purpose: 'document',
        },
        signal,
      },
      UploadUrlResponseSchema,
      'upload-URL',
      'nonbillable-write',
    );
  }

  public async streamUpload(
    uploadUrl: string,
    filePath: string,
    contentType: string,
    sizeBytes: number,
    signal?: AbortSignal,
  ): Promise<void> {
    const source = createReadStream(filePath);
    const request: RequestInit & { duplex: 'half' } = {
      method: 'PUT',
      headers: {
        'Content-Type': contentType,
        'Content-Length': String(sizeBytes),
      },
      body: source as unknown as BodyInit,
      duplex: 'half',
      signal: signal ?? null,
    };

    try {
      const response = await this.fetchImplementation(uploadUrl, request);
      if (!response.ok) {
        throw await this.signedTransferError(
          response,
          uploadUrl,
          'Signed upload failed',
          EXIT_CODES.uploadReadFailure,
        );
      }
      this.uploadByteCount += sizeBytes;
    } catch (error) {
      source.destroy();
      throw asSdxError(
        error,
        `Unable to stream ${basename(filePath)} to signed storage.`,
        EXIT_CODES.uploadReadFailure,
      );
    }
  }

  public processUploadedDocument(
    uploadId: string,
    sessionId: string,
    filename: string,
    signal?: AbortSignal,
  ): Promise<ProcessDocumentResponse> {
    return this.apiJson(
      `/v1/uploads/${encodeURIComponent(uploadId)}/process`,
      {
        method: 'POST',
        body: {
          session_id: sessionId,
          filename,
          parse_mode: 'document',
          return_html: false,
        },
        signal,
      },
      ProcessDocumentResponseSchema,
      'uploaded-document parse',
      'nonbillable-write',
    );
  }

  public startAsyncEdit(
    sessionId: string,
    message: string,
    signal?: AbortSignal,
    options: AsyncEditOptions = {},
  ): Promise<AsyncChatResponse> {
    return this.apiJson(
      '/v1/chat/async',
      {
        method: 'POST',
        body: {
          message,
          session_id: sessionId,
          approval_mode: 'ask_every_time',
          response_mode: 'full',
          ...(options.modelTier ? { model_tier: options.modelTier } : {}),
          ...(options.documentId ? { document_id: options.documentId } : {}),
        },
        signal,
      },
      AsyncChatResponseSchema,
      'async-edit',
      'billable-write',
    );
  }
  public getJob(jobId: string, signal?: AbortSignal): Promise<ApiJob> {
    return this.apiJson(
      `/v1/jobs/${encodeURIComponent(jobId)}`,
      { method: 'GET', body: undefined, signal },
      JobResponseSchema,
      'job',
      'read',
    );
  }

  public async submitApprovalDecisions(
    sessionId: string,
    jobId: string,
    decisions: readonly ApprovalDecision[],
    signal?: AbortSignal,
  ): Promise<void> {
    await this.apiJson(
      `/v1/chat/${encodeURIComponent(sessionId)}/approve`,
      {
        method: 'POST',
        body: {
          job_id: jobId,
          approved: true,
          changes: decisions,
        },
        signal,
      },
      ApprovalResponseSchema,
      'approval',
      'nonbillable-write',
    );
  }

  public async continueLargeEdit(
    sessionId: string,
    jobId: string,
    shouldContinue: boolean,
    signal?: AbortSignal,
  ): Promise<void> {
    await this.apiJson(
      `/v1/chat/${encodeURIComponent(sessionId)}/continue`,
      {
        method: 'POST',
        body: { job_id: jobId, continue: shouldContinue },
        signal,
      },
      ContinueResponseSchema,
      'continuation',
      'nonbillable-write',
    );
  }

  public requestDownloadUrl(
    sessionId: string,
    format: ExportFormat,
    filename: string,
    signal?: AbortSignal,
  ): Promise<DownloadUrlResponse> {
    return this.apiJson(
      '/v1/downloads',
      {
        method: 'POST',
        body: { session_id: sessionId, format, filename },
        signal,
      },
      DownloadUrlResponseSchema,
      'download-URL',
      'nonbillable-write',
    );
  }

  public async exportDocument(
    sessionId: string,
    format: ExportFormat,
    signal?: AbortSignal,
  ): Promise<Response> {
    const attempted = await this.fetchWithRetry(
      new URL('/v1/documents/export', this.baseUrl),
      {
        method: 'POST',
        headers: {
          Accept: 'application/octet-stream',
          Authorization: `Bearer ${this.apiKey}`,
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({ session_id: sessionId, format }),
        signal: signal ?? null,
      },
      'document export', 'nonbillable-write', signal, true,
    );
    const { response } = attempted;
    if (!response.ok) {
      throw await this.apiHttpError(response, 'document export', attempted.attempt, attempted.plan);
    }
    if (response.body === null) {
      throw new SdxError(
        'Document export returned no response body.',
        EXIT_CODES.exportWriteFailure,
      );
    }
    return response;
  }

  public async streamDownloadAtomically(
    downloadUrl: string,
    destination: string,
    signal?: AbortSignal,
    overwrite = false,
    verifyTemporary?: (temporaryPath: string) => Promise<void>,
  ): Promise<DownloadResult> {
    await cleanupDeadDownloadTemporaries(destination);
    const attempted = await this.fetchWithRetry(downloadUrl, {
      method: 'GET',
      signal: signal ?? null,
    }, 'signed download', 'signed-download', signal, false);
    const { response } = attempted;

    if (!response.ok) {
      throw await this.signedTransferError(
        response,
        downloadUrl,
        'Signed download failed',
        EXIT_CODES.exportWriteFailure,
      );
    }
    if (response.body === null) {
      throw new SdxError(
        'Export download returned no response body.',
        EXIT_CODES.exportWriteFailure,
      );
    }

    const temporary = join(
      dirname(destination),
      `.${basename(destination)}.${process.pid}.${randomUUID()}.tmp`,
    );
    try {
      const readable = Readable.fromWeb(
        response.body as never,
      );
      await pipeline(readable, createWriteStream(temporary, { flags: 'wx' }));
      const outputStat = await stat(temporary);
      if (outputStat.size === 0) {
        throw new SdxError(
          'Export download was empty.',
          EXIT_CODES.exportWriteFailure,
        );
      }
      await verifyTemporary?.(temporary);
      if (overwrite) {
        await rename(temporary, destination);
      } else {
        await link(temporary, destination);
        await unlink(temporary);
      }
      this.downloadByteCount += outputStat.size;
      return {
        bytes: outputStat.size,
        warnings: this.parseExportWarnings(response.headers.get('x-export-warnings')),
      };
    } catch (error) {
      await unlink(temporary).catch(() => undefined);
      throw asSdxError(
        error,
        `Unable to finalize export at ${destination}.`,
        EXIT_CODES.exportWriteFailure,
      );
    }
  }

  private async fetchWithRetry(
    target: URL | string,
    init: RequestInit,
    operation: string,
    safety: RetrySafety,
    signal: AbortSignal | undefined,
    countApiCall: boolean,
  ): Promise<AttemptedResponse> {
    const deadlineMs = this.retryPolicy.now() + this.retryBudgetMs;
    let attempt = 0;
    while (true) {
      attempt += 1;
      if (countApiCall) this.apiCallCount += 1;
      let response: Response;
      try {
        response = await this.fetchImplementation(target, init);
      } catch (error) {
        const plan = this.retryPolicy.transportPlan(safety, attempt, deadlineMs);
        if (plan.retry) {
          this.onRetry?.(plan, operation);
          await this.retryPolicy.wait(plan, signal);
          continue;
        }
        const unknown = safety === 'billable-write' || safety === 'nonbillable-write';
        throw new SdxError(
          unknown
            ? `SuperDocs ${operation} ended before its remote outcome was known; it was not retried.`
            : `Unable to reach SuperDocs for ${operation} after ${attempt} attempt(s).`,
          EXIT_CODES.apiFailure,
          {
            httpStatus: undefined, requestId: undefined, retryAfter: undefined,
            usageLimit: undefined, usageUsed: undefined, usageRemaining: undefined,
            details: { reason: plan.reason }, retryable: false, retryAfterSeconds: null,
            attemptCount: attempt, retryKind: plan.kind,
            remoteState: unknown ? 'unknown' : 'known',
          },
          { cause: error },
        );
      }
      const plan = this.retryPolicy.responsePlan({
        status: response.status,
        retryAfter: response.headers.get('retry-after'),
        contentType: response.headers.get('content-type'),
        safety, attempt, deadlineMs,
      });
      if (!response.ok && plan.retry) {
        await response.body?.cancel().catch(() => undefined);
        this.onRetry?.(plan, operation);
        await this.retryPolicy.wait(plan, signal);
        continue;
      }
      return { response, attempt, plan };
    }
  }

  private async apiJson<TSchema extends z.ZodTypeAny>(
    path: string,
    options: RequestOptions,
    schema: TSchema,
    operation: string,
    safety: RetrySafety,
  ): Promise<z.output<TSchema>> {
    const url = new URL(path, this.baseUrl);
    const headers = new Headers({
      Accept: 'application/json',
      Authorization: `Bearer ${this.apiKey}`,
    });
    let body: string | undefined;
    if (options.body !== undefined) {
      headers.set('Content-Type', 'application/json');
      body = JSON.stringify(options.body);
    }
    const attempted = await this.fetchWithRetry(url, {
      method: options.method,
      headers,
      body: body ?? null,
      signal: options.signal ?? null,
    }, operation, safety, options.signal, true);
    const { response } = attempted;
    if (!response.ok) {
      throw await this.apiHttpError(response, operation, attempted.attempt, attempted.plan);
    }

    let payload: unknown;
    try {
      payload = await response.json();
    } catch (error) {
      throw schemaMismatch(`${operation} JSON`, error as Error);
    }
    const parsed = schema.safeParse(payload);
    if (!parsed.success) {
      throw schemaMismatch(operation, parsed.error);
    }
    return parsed.data;
  }

  private async apiHttpError(
    response: Response,
    operation: string,
    attempt = 1,
    retryPlan?: RetryPlan,
  ): Promise<SdxError> {
    const raw = (await response.text()).slice(0, 8192);
    let details: unknown = raw;
    try {
      const candidate: unknown = JSON.parse(raw);
      const parsed = ApiErrorBodySchema.safeParse(candidate);
      details = parsed.success ? parsed.data : candidate;
    } catch {
      // The docs warn that gateway 413s and some 429s can be non-JSON.
    }
    const exitCode: ExitCode =
      response.status === 401
        ? EXIT_CODES.authenticationFailure
        : response.status === 429
          ? EXIT_CODES.rateLimitFailure
          : EXIT_CODES.apiFailure;
    const retryMessage = response.status === 429
      ? retryPlan?.retryAfterSeconds !== null && retryPlan?.retryAfterSeconds !== undefined
        ? ` Retry after ${retryPlan.retryAfterSeconds} second(s); ${retryPlan.reason}.`
        : ` ${retryPlan?.reason ?? 'Retry budget exhausted.'}.`
      : '';
    return new SdxError(
      redactText(`SuperDocs ${operation} failed with HTTP ${response.status}.${retryMessage}`, [
        this.apiKey,
      ]),
      exitCode,
      {
        httpStatus: response.status,
        requestId:
          response.headers.get('x-request-id') ??
          response.headers.get('request-id') ??
          undefined,
        retryAfter: response.headers.get('retry-after') ?? undefined,
        usageLimit: response.headers.get('x-usage-limit') ?? undefined,
        usageUsed: response.headers.get('x-usage-used') ?? undefined,
        usageRemaining: response.headers.get('x-usage-remaining') ?? undefined,
        details: redactUnknown(details),
        retryable: retryPlan?.retry ?? false,
        retryAfterSeconds: retryPlan?.retryAfterSeconds ?? null,
        attemptCount: attempt,
        retryKind: retryPlan?.kind ?? 'none',
        remoteState: 'known-rejected',
      },
    );
  }

  private async signedTransferError(
    response: Response,
    url: string,
    message: string,
    exitCode: ExitCode,
  ): Promise<SdxError> {
    const details = redactText((await response.text()).slice(0, 4096), [
      this.apiKey,
    ]);
    return new SdxError(
      `${message} with HTTP ${response.status} at ${redactUrl(url)}.`,
      exitCode,
      {
        httpStatus: response.status,
        requestId: response.headers.get('x-request-id') ?? undefined,
        retryAfter: response.headers.get('retry-after') ?? undefined,
        usageLimit: undefined,
        usageUsed: undefined,
        usageRemaining: undefined,
        details,
      },
    );
  }

  private parseExportWarnings(value: string | null): readonly string[] {
    if (value === null || value.length === 0) {
      return [];
    }
    try {
      const decoded = JSON.parse(Buffer.from(value, 'base64').toString('utf8')) as unknown;
      if (!Array.isArray(decoded)) {
        return ['Export returned an unreadable warnings header.'];
      }
      return decoded.map((warning) =>
        typeof warning === 'object' && warning !== null && 'message' in warning
          ? String(warning.message)
          : 'Export completed with a warning.',
      );
    } catch {
      return ['Export returned an unreadable warnings header.'];
    }
  }
}
