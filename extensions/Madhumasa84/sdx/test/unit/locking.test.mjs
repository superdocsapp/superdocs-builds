import assert from 'node:assert/strict';
import { mkdir, mkdtemp, rm, writeFile } from 'node:fs/promises';
import { join } from 'node:path';
import test from 'node:test';

import { SessionStore } from '../../dist/sessions/store.js';
import { withFileLock } from '../../dist/storage/lock.js';

test('bounded lock contention fails actionably and releases cleanly', async () => {
  const directory = await mkdtemp('/tmp/sdx-lock-contention-'); const target = join(directory, 'state.json');
  let release;
  const held = withFileLock(target, () => new Promise((resolve) => { release = resolve; }));
  await new Promise((resolve) => setTimeout(resolve, 20));
  await assert.rejects(withFileLock(target, async () => undefined, { timeoutMs: 30, pollMs: 5 }), /Timed out waiting for lock/);
  release(); await held;
  await withFileLock(target, async () => undefined, { timeoutMs: 30 });
  await rm(directory, { recursive: true, force: true });
});

test('dead-owner stale lock is recovered safely', async () => {
  const directory = await mkdtemp('/tmp/sdx-lock-stale-'); const target = join(directory, 'state.json');
  await mkdir(`${target}.lock`, { mode: 0o700 });
  await writeFile(join(`${target}.lock`, 'owner.json'), `${JSON.stringify({ pid: 999_999, createdAt: new Date().toISOString(), nonce: '11111111-1111-4111-8111-111111111111' })}\n`, { mode: 0o600 });
  let entered = false;
  await withFileLock(target, async () => { entered = true; }, { timeoutMs: 100 });
  assert.equal(entered, true);
  await rm(directory, { recursive: true, force: true });
});

test('concurrent session writes retain every record with 0600 state', async () => {
  const directory = await mkdtemp('/tmp/sdx-lock-updates-'); const previous = process.env.SDX_STATE_DIR;
  process.env.SDX_STATE_DIR = directory;
  try {
    const store = new SessionStore(); const stamp = new Date().toISOString();
    await Promise.all(Array.from({ length: 12 }, (_, index) => store.put({
      name: `session-${index}`, serverSessionId: `server-${index}`,
      durableDocumentId: null, sessionDocumentId: null, canonicalSourcePath: `/tmp/source-${index}.docx`,
      sourceSha256: String(index).padStart(64, '0'), lastJobId: null, lastExportFormat: null,
      lastOutputPath: null, createdAt: stamp, updatedAt: stamp,
    })));
    assert.equal((await store.list()).length, 12);
    assert.equal(await store.permissions(), 0o600);
  } finally {
    if (previous === undefined) delete process.env.SDX_STATE_DIR; else process.env.SDX_STATE_DIR = previous;
    await rm(directory, { recursive: true, force: true });
  }
});
