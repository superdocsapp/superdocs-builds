import { createHash, randomUUID } from 'node:crypto';
import { chmod, mkdir, readFile, rename, stat, unlink, writeFile } from 'node:fs/promises';
import { homedir } from 'node:os';
import { dirname, join } from 'node:path';

import { z } from 'zod';

import { SdxError } from '../api/errors.js';
import { ExportFormatSchema } from '../api/schemas.js';
import { EXIT_CODES } from '../core/exit-codes.js';
import { withFileLock } from '../storage/lock.js';

export const OperationStateSchema = z.enum([
  'prepared', 'upload-prepared', 'upload-completed', 'document-processed',
  'submission-started', 'acknowledged', 'waiting-approval', 'waiting-continuation',
  'approval-decided', 'continuation-decided',
  'completed', 'terminal', 'export-requested', 'download-completed', 'unknown', 'failed',
]);

export const OperationRecordSchema = z.object({
  operationId: z.string().uuid(),
  kind: z.literal('async-edit'),
  fingerprint: z.string().regex(/^[a-f0-9]{64}$/),
  instructionSha256: z.string().regex(/^[a-f0-9]{64}$/),
  sourceSha256: z.string().regex(/^[a-f0-9]{64}$/),
  sourcePath: z.string().min(1).optional(),
  sourceFilename: z.string().min(1).optional(),
  sourceContentType: z.string().min(1).optional(),
  sourceSize: z.number().int().positive().optional(),
  sessionId: z.string().min(1),
  sessionName: z.string().nullable(),
  jobId: z.string().nullable(),
  uploadId: z.string().nullable().optional(),
  documentId: z.string().nullable().optional(),
  state: OperationStateSchema,
  exportFormat: ExportFormatSchema.nullable(),
  outputPath: z.string().nullable(),
  createdAt: z.string().datetime(),
  updatedAt: z.string().datetime(),
}).strict();

const LedgerSchema = z.object({
  version: z.literal(1),
  operations: z.record(z.string(), OperationRecordSchema),
}).strict();

export type OperationRecord = z.infer<typeof OperationRecordSchema>;
export type OperationState = z.infer<typeof OperationStateSchema>;

export interface PrepareOperationInput {
  readonly instruction: string;
  readonly sourceSha256: string;
  readonly sourcePath: string;
  readonly sourceFilename: string;
  readonly sourceContentType: string;
  readonly sourceSize: number;
  readonly sessionId: string;
  readonly sessionName: string | null;
  readonly exportFormat: z.infer<typeof ExportFormatSchema> | null;
  readonly outputPath: string | null;
  readonly now?: Date;
}

function stateDirectory(): string { return process.env.SDX_STATE_DIR ?? join(homedir(), '.sdx'); }
export function operationLedgerPath(): string { return join(stateDirectory(), 'operations.json'); }

export function sha256Text(value: string): string {
  return createHash('sha256').update(value, 'utf8').digest('hex');
}

export function operationFingerprint(input: {
  readonly sessionId: string; readonly sourceSha256: string; readonly instructionSha256: string;
}): string {
  return sha256Text(JSON.stringify({
    kind: 'async-edit', sessionId: input.sessionId,
    sourceSha256: input.sourceSha256, instructionSha256: input.instructionSha256,
  }));
}

async function readLedger(path: string): Promise<z.infer<typeof LedgerSchema>> {
  let raw: string;
  try { raw = await readFile(path, 'utf8'); }
  catch (error) {
    if ((error as NodeJS.ErrnoException).code === 'ENOENT') return { version: 1, operations: {} };
    throw new SdxError('Unable to read the operation ledger.', EXIT_CODES.invalidInput, undefined, { cause: error });
  }
  try {
    const parsed = LedgerSchema.safeParse(JSON.parse(raw) as unknown);
    if (!parsed.success) throw parsed.error;
    return parsed.data;
  } catch (error) {
    throw new SdxError(`Operation ledger is corrupt at ${path}; move it aside and retry.`, EXIT_CODES.invalidInput, undefined, { cause: error });
  }
}

async function writeLedger(path: string, value: z.infer<typeof LedgerSchema>): Promise<void> {
  await mkdir(dirname(path), { recursive: true, mode: 0o700 }); await chmod(dirname(path), 0o700);
  const temporary = `${path}.${process.pid}.${randomUUID()}.tmp`;
  try {
    await writeFile(temporary, `${JSON.stringify(value, null, 2)}\n`, { encoding: 'utf8', mode: 0o600, flag: 'wx' });
    await chmod(temporary, 0o600); await rename(temporary, path); await chmod(path, 0o600);
  } catch (error) {
    await unlink(temporary).catch(() => undefined);
    throw new SdxError('Unable to write the operation ledger.', EXIT_CODES.invalidInput, undefined, { cause: error });
  }
}

function unresolved(record: OperationRecord): boolean {
  return !['download-completed', 'terminal', 'failed'].includes(record.state);
}

export class OperationLedger {
  public readonly path = operationLedgerPath();

  public async list(): Promise<OperationRecord[]> {
    return Object.values((await readLedger(this.path)).operations).sort((a, b) => a.createdAt.localeCompare(b.createdAt));
  }

  public async get(operationId: string): Promise<OperationRecord | undefined> {
    return (await readLedger(this.path)).operations[operationId];
  }

  public async byJob(jobId: string): Promise<OperationRecord | undefined> {
    return (await this.list()).find((record) => record.jobId === jobId);
  }

  public async unresolvedForSession(sessionId: string): Promise<OperationRecord[]> {
    return (await this.list()).filter((record) => record.sessionId === sessionId && unresolved(record));
  }

  public async prepare(input: PrepareOperationInput): Promise<OperationRecord> {
    return withFileLock(this.path, async () => {
      const ledger = await readLedger(this.path);
      const active = Object.values(ledger.operations).filter((record) => record.sessionId === input.sessionId && unresolved(record));
      if (active.length > 0) {
        const existing = active[0];
        throw new SdxError(
          existing?.jobId
            ? `Session already has resumable job ${existing.jobId}; run \`sdx resume ${existing.jobId}\`.`
            : `Session has operation ${existing?.operationId ?? 'unknown'} with an unknown remote outcome; do not resubmit automatically.`,
          EXIT_CODES.apiFailure,
          {
            httpStatus: undefined, requestId: undefined, retryAfter: undefined,
            usageLimit: undefined, usageUsed: undefined, usageRemaining: undefined,
            details: { recovery: existing?.jobId ? 'resume-job' : 'manual-reconciliation-required' },
            retryable: false, retryAfterSeconds: null, attemptCount: 0, retryKind: 'none',
            remoteState: existing?.jobId ? 'known' : 'unknown', ...(existing ? { operationId: existing.operationId } : {}),
          },
        );
      }
      const stamp = (input.now ?? new Date()).toISOString();
      const instructionSha256 = sha256Text(input.instruction);
      const record: OperationRecord = {
        operationId: randomUUID(), kind: 'async-edit', sourceSha256: input.sourceSha256,
        sourcePath: input.sourcePath, sourceFilename: input.sourceFilename,
        sourceContentType: input.sourceContentType, sourceSize: input.sourceSize,
        instructionSha256, fingerprint: operationFingerprint({ sessionId: input.sessionId, sourceSha256: input.sourceSha256, instructionSha256 }),
        sessionId: input.sessionId, sessionName: input.sessionName, jobId: null,
        uploadId: null, documentId: null, state: 'prepared',
        exportFormat: input.exportFormat, outputPath: input.outputPath, createdAt: stamp, updatedAt: stamp,
      };
      await writeLedger(this.path, { version: 1, operations: { ...ledger.operations, [record.operationId]: record } });
      return record;
    });
  }

  public async transition(operationId: string, state: OperationState, patch: Partial<Pick<OperationRecord, 'jobId' | 'uploadId' | 'documentId' | 'outputPath' | 'exportFormat'>> = {}, now = new Date()): Promise<OperationRecord> {
    return withFileLock(this.path, async () => {
      const ledger = await readLedger(this.path); const existing = ledger.operations[operationId];
      if (!existing) throw new SdxError(`Unknown operation ledger ID: ${operationId}`, EXIT_CODES.invalidInput);
      const updated = OperationRecordSchema.parse({ ...existing, ...patch, state, updatedAt: now.toISOString() });
      await writeLedger(this.path, { version: 1, operations: { ...ledger.operations, [operationId]: updated } });
      return updated;
    });
  }

  public async permissions(): Promise<number | null> {
    try { return (await stat(this.path)).mode & 0o777; }
    catch (error) { if ((error as NodeJS.ErrnoException).code === 'ENOENT') return null; throw error; }
  }
}
