import { randomUUID, createHash } from 'node:crypto';
import { chmod, mkdir, readFile, rename, rm, stat, writeFile } from 'node:fs/promises';
import { homedir } from 'node:os';
import { basename, dirname, join } from 'node:path';

import { z } from 'zod';

import { SdxError } from '../api/errors.js';
import { EXIT_CODES } from '../core/exit-codes.js';

const OwnerSchema = z.object({ pid: z.number().int().positive(), createdAt: z.string().datetime(), nonce: z.string().uuid() }).strict();

export interface LockOptions {
  readonly timeoutMs?: number;
  readonly staleMs?: number;
  readonly pollMs?: number;
  readonly signal?: AbortSignal;
  readonly clock?: () => number;
  readonly sleeper?: (delayMs: number, signal?: AbortSignal) => Promise<void>;
}

function sleep(delayMs: number, signal?: AbortSignal): Promise<void> {
  return new Promise((resolve, reject) => {
    if (signal?.aborted) { reject(signal.reason ?? new DOMException('Aborted', 'AbortError')); return; }
    const timer = setTimeout(resolve, delayMs);
    const abort = (): void => { clearTimeout(timer); reject(signal?.reason ?? new DOMException('Aborted', 'AbortError')); };
    signal?.addEventListener('abort', abort, { once: true });
  });
}

function processAlive(pid: number): boolean {
  try { process.kill(pid, 0); return true; }
  catch (error) { return (error as NodeJS.ErrnoException).code === 'EPERM'; }
}

async function stale(lockPath: string, staleMs: number, now: number): Promise<boolean> {
  try {
    const ownerRaw = await readFile(join(lockPath, 'owner.json'), 'utf8');
    const owner = OwnerSchema.safeParse(JSON.parse(ownerRaw) as unknown);
    if (owner.success && !processAlive(owner.data.pid)) return true;
  } catch {
    // A missing/partial owner is stale only after the age threshold.
  }
  try { return now - (await stat(lockPath)).mtimeMs > staleMs; }
  catch (error) { return (error as NodeJS.ErrnoException).code === 'ENOENT'; }
}

async function recoverStale(lockPath: string): Promise<void> {
  const moved = `${lockPath}.stale.${process.pid}.${randomUUID()}`;
  try { await rename(lockPath, moved); }
  catch (error) { if ((error as NodeJS.ErrnoException).code === 'ENOENT') return; throw error; }
  await rm(moved, { recursive: true, force: true });
}

export async function withFileLock<T>(targetPath: string, action: () => Promise<T>, options: LockOptions = {}): Promise<T> {
  const lockPath = `${targetPath}.lock`;
  const clock = options.clock ?? Date.now;
  const wait = options.sleeper ?? sleep;
  const timeoutMs = options.timeoutMs ?? 2_000;
  const staleMs = options.staleMs ?? 30_000;
  const pollMs = options.pollMs ?? 25;
  const deadline = clock() + timeoutMs;
  await mkdir(dirname(targetPath), { recursive: true, mode: 0o700 }); await chmod(dirname(targetPath), 0o700);
  while (true) {
    try {
      await mkdir(lockPath, { mode: 0o700 }); await chmod(lockPath, 0o700);
      await writeFile(join(lockPath, 'owner.json'), `${JSON.stringify({ pid: process.pid, createdAt: new Date(clock()).toISOString(), nonce: randomUUID() })}\n`, { mode: 0o600, flag: 'wx' });
      break;
    } catch (error) {
      if ((error as NodeJS.ErrnoException).code !== 'EEXIST') throw new SdxError(`Unable to acquire state lock for ${basename(targetPath)}.`, EXIT_CODES.invalidInput, undefined, { cause: error });
      if (await stale(lockPath, staleMs, clock())) { await recoverStale(lockPath); continue; }
      if (clock() + pollMs > deadline) throw new SdxError(`Timed out waiting for lock on ${basename(targetPath)}; another sdx process is using it.`, EXIT_CODES.invalidInput);
      await wait(pollMs, options.signal);
    }
  }
  try { return await action(); }
  finally { await rm(lockPath, { recursive: true, force: true }); }
}

function stateDirectory(): string { return process.env.SDX_STATE_DIR ?? join(homedir(), '.sdx'); }

export function workflowLockPath(sessionName: string): string {
  const digest = createHash('sha256').update(sessionName, 'utf8').digest('hex').slice(0, 32);
  return join(stateDirectory(), 'locks', `session-${digest}`);
}

export function withSessionLock<T>(sessionName: string, action: () => Promise<T>, options: LockOptions = {}): Promise<T> {
  return withFileLock(workflowLockPath(sessionName), action, { timeoutMs: 2_000, staleMs: 30_000, ...options });
}
