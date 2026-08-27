import { open, readFile, rm, stat } from 'node:fs/promises';
import { dirname } from 'node:path';
import { ensurePrivateDir } from './io.js';
import { ChangelogError } from './errors.js';

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

function ownerAlive(pid) {
  try { process.kill(pid, 0); return true; } catch { return false; }
}

export async function acquireCanonicalLock(canonicalPath, { timeoutMs = 3000, staleMs = 30_000, pollMs = 15 } = {}) {
  const lockPath = `${canonicalPath}.lock`;
  await ensurePrivateDir(dirname(lockPath));
  const deadline = Date.now() + timeoutMs;
  while (Date.now() <= deadline) {
    try {
      const handle = await open(lockPath, 'wx', 0o600);
      await handle.writeFile(JSON.stringify({ pid: process.pid, created_at: new Date().toISOString() }));
      await handle.close();
      return async () => { await rm(lockPath, { force: true }); };
    } catch (error) {
      if (error?.code !== 'EEXIST') throw error;
      try {
        const info = await stat(lockPath);
        const owner = JSON.parse(await readFile(lockPath, 'utf8'));
        if (Date.now() - info.mtimeMs > staleMs && !ownerAlive(Number(owner.pid))) {
          await rm(lockPath, { force: true });
          continue;
        }
      } catch (inspectError) {
        if (inspectError?.code === 'ENOENT') continue;
      }
      await sleep(pollMs);
    }
  }
  throw new ChangelogError(`canonical changelog is locked: ${canonicalPath}`, 'LOCK_TIMEOUT', 20);
}

export async function withCanonicalLock(canonicalPath, fn, options) {
  const release = await acquireCanonicalLock(canonicalPath, options);
  try { return await fn(); } finally { await release(); }
}
