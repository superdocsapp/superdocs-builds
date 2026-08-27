import { createHash, randomUUID } from 'node:crypto';
import { chmod, mkdir, readFile, rename, stat, unlink, writeFile } from 'node:fs/promises';
import { createReadStream } from 'node:fs';
import { homedir } from 'node:os';
import { dirname, join } from 'node:path';

import { z } from 'zod';

import { SdxError } from '../api/errors.js';
import { ExportFormatSchema } from '../api/schemas.js';
import { EXIT_CODES } from '../core/exit-codes.js';
import { withFileLock } from '../storage/lock.js';

const StoredChangeSchema = z.object({
  id: z.string().min(1),
  operation: z.enum(['edit', 'create', 'delete']),
  chunkId: z.string().nullable(),
  documentId: z.string().nullable(),
  oldContent: z.string().nullable(),
  newContent: z.string().nullable(),
  explanation: z.string().nullable(),
}).strict();

export const SessionRecordSchema = z.object({
  name: z.string().min(1),
  serverSessionId: z.string().min(1),
  durableDocumentId: z.string().nullable(),
  sessionDocumentId: z.string().nullable(),
  canonicalSourcePath: z.string().min(1),
  sourceSha256: z.string().regex(/^[a-f0-9]{64}$/),
  lastJobId: z.string().nullable(),
  lastExportFormat: ExportFormatSchema.nullable(),
  lastOutputPath: z.string().nullable(),
  createdAt: z.string().datetime(),
  updatedAt: z.string().datetime(),
}).strict();

export const PendingJobSchema = z.object({
  jobId: z.string().min(1),
  sessionId: z.string().min(1),
  sessionName: z.string().nullable(),
  documentPath: z.string().nullable(),
  documentName: z.string().min(1),
  documentFormat: z.string().nullable(),
  documentId: z.string().nullable(),
  outputPath: z.string().nullable(),
  exportFormat: ExportFormatSchema.nullable(),
  changes: z.array(StoredChangeSchema),
  createdAt: z.string().datetime(),
  updatedAt: z.string().datetime(),
}).strict();

const SessionFileSchema = z.object({ version: z.literal(1), sessions: z.record(z.string(), SessionRecordSchema) }).strict();
const JobFileSchema = z.object({ version: z.literal(1), jobs: z.record(z.string(), PendingJobSchema) }).strict();

export type SessionRecord = z.infer<typeof SessionRecordSchema>;
export type PendingJob = z.infer<typeof PendingJobSchema>;

function stateDirectory(): string {
  return process.env.SDX_STATE_DIR ?? join(homedir(), '.sdx');
}

export function sessionStatePath(): string { return join(stateDirectory(), 'sessions.json'); }
export function pendingJobStatePath(): string { return join(stateDirectory(), 'pending-jobs.json'); }

async function readState<T>(path: string, schema: z.ZodType<T>, fallback: T, label: string): Promise<T> {
  let raw: string;
  try { raw = await readFile(path, 'utf8'); }
  catch (error) {
    if ((error as NodeJS.ErrnoException).code === 'ENOENT') return fallback;
    throw new SdxError(`Unable to read ${label} state.`, EXIT_CODES.invalidInput, undefined, { cause: error });
  }
  try {
    const parsed = schema.safeParse(JSON.parse(raw) as unknown);
    if (!parsed.success) throw parsed.error;
    return parsed.data;
  } catch (error) {
    throw new SdxError(`Stored ${label} state is corrupt at ${path}; move it aside and retry.`, EXIT_CODES.invalidInput, undefined, { cause: error });
  }
}

async function atomicState(path: string, value: unknown): Promise<void> {
  await mkdir(dirname(path), { recursive: true, mode: 0o700 });
  await chmod(dirname(path), 0o700);
  const temporary = `${path}.${process.pid}.${randomUUID()}.tmp`;
  try {
    await writeFile(temporary, `${JSON.stringify(value, null, 2)}\n`, { encoding: 'utf8', mode: 0o600, flag: 'wx' });
    await chmod(temporary, 0o600);
    await rename(temporary, path);
    await chmod(path, 0o600);
  } catch (error) {
    await unlink(temporary).catch(() => undefined);
    throw new SdxError(`Unable to write state at ${path}.`, EXIT_CODES.invalidInput, undefined, { cause: error });
  }
}

export function validateAlias(name: string): string {
  if (!/^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$/.test(name)) {
    throw new SdxError('Session/profile names must use letters, digits, dot, underscore, or hyphen.', EXIT_CODES.invalidInput);
  }
  return name;
}

export async function sha256File(path: string): Promise<string> {
  const hash = createHash('sha256');
  const source = createReadStream(path);
  for await (const chunk of source) hash.update(chunk as Buffer);
  return hash.digest('hex');
}

export class SessionStore {
  public readonly path = sessionStatePath();
  public async list(): Promise<SessionRecord[]> {
    const state = await readState(this.path, SessionFileSchema, { version: 1 as const, sessions: {} }, 'session');
    return Object.values(state.sessions).sort((a, b) => a.name.localeCompare(b.name));
  }
  public async get(name: string): Promise<SessionRecord | undefined> {
    validateAlias(name);
    return (await readState(this.path, SessionFileSchema, { version: 1 as const, sessions: {} }, 'session')).sessions[name];
  }
  public async put(record: SessionRecord): Promise<void> {
    validateAlias(record.name);
    await withFileLock(this.path, async () => {
      const state = await readState(this.path, SessionFileSchema, { version: 1 as const, sessions: {} }, 'session');
      await atomicState(this.path, { version: 1, sessions: { ...state.sessions, [record.name]: SessionRecordSchema.parse(record) } });
    });
  }
  public async remove(name: string): Promise<boolean> {
    validateAlias(name);
    return withFileLock(this.path, async () => {
      const state = await readState(this.path, SessionFileSchema, { version: 1 as const, sessions: {} }, 'session');
      if (state.sessions[name] === undefined) return false;
      const sessions = { ...state.sessions }; delete sessions[name];
      await atomicState(this.path, { version: 1, sessions });
      return true;
    });
  }
  public async permissions(): Promise<number | null> {
    try { return (await stat(this.path)).mode & 0o777; }
    catch (error) { if ((error as NodeJS.ErrnoException).code === 'ENOENT') return null; throw error; }
  }
}

export class PendingJobStore {
  public readonly path = pendingJobStatePath();
  public async get(jobId: string): Promise<PendingJob | undefined> {
    return (await readState(this.path, JobFileSchema, { version: 1 as const, jobs: {} }, 'pending-job')).jobs[jobId];
  }
  public async list(): Promise<PendingJob[]> {
    return Object.values((await readState(this.path, JobFileSchema, { version: 1 as const, jobs: {} }, 'pending-job')).jobs)
      .sort((a, b) => a.createdAt.localeCompare(b.createdAt));
  }
  public async put(record: PendingJob): Promise<void> {
    await withFileLock(this.path, async () => {
      const state = await readState(this.path, JobFileSchema, { version: 1 as const, jobs: {} }, 'pending-job');
      await atomicState(this.path, { version: 1, jobs: { ...state.jobs, [record.jobId]: PendingJobSchema.parse(record) } });
    });
  }
  public async remove(jobId: string): Promise<void> {
    await withFileLock(this.path, async () => {
      const state = await readState(this.path, JobFileSchema, { version: 1 as const, jobs: {} }, 'pending-job');
      if (state.jobs[jobId] === undefined) return;
      const jobs = { ...state.jobs }; delete jobs[jobId];
      await atomicState(this.path, { version: 1, jobs });
    });
  }
  public async permissions(): Promise<number | null> {
    try { return (await stat(this.path)).mode & 0o777; }
    catch (error) { if ((error as NodeJS.ErrnoException).code === 'ENOENT') return null; throw error; }
  }
}
