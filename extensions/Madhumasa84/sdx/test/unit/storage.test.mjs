import assert from 'node:assert/strict';
import { mkdtemp, readFile, rm, stat, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import test from 'node:test';

import { readStoredCredential, resolveCredential, storeCredential } from '../../dist/security/credentials.js';
import { SessionStore } from '../../dist/sessions/store.js';

test('credentials and session state are atomically stored with restrictive permissions', async () => {
  const directory = await mkdtemp(join('/tmp', 'sdx-storage-'));
  process.env.SDX_CREDENTIAL_PATH = join(directory, 'credentials.json');
  const credentialFile = process.env.SDX_CREDENTIAL_PATH;
  process.env.SDX_STATE_DIR = directory;
  try {
    await storeCredential('sk_fixture_secret');
    assert.equal((await stat(credentialFile)).mode & 0o777, 0o600);
    assert.equal(await readStoredCredential(), 'sk_fixture_secret');
    const sessions = new SessionStore();
    await sessions.put({
      name: 'work', serverSessionId: 'session-1', durableDocumentId: null, sessionDocumentId: null,
      canonicalSourcePath: '/tmp/source.md', sourceSha256: 'a'.repeat(64), lastJobId: null,
      lastExportFormat: null, lastOutputPath: null, createdAt: '2026-08-06T00:00:00.000Z', updatedAt: '2026-08-06T00:00:00.000Z',
    });
    assert.equal((await stat(sessions.path)).mode & 0o777, 0o600);
    assert.doesNotMatch(await readFile(sessions.path, 'utf8'), /fixture_secret/);
  } finally {
    delete process.env.SDX_CREDENTIAL_PATH; delete process.env.SDX_STATE_DIR;
    await rm(directory, { recursive: true, force: true });
  }
});

test('environment credential takes precedence and corrupt session state fails safely', async () => {
  const directory = await mkdtemp(join('/tmp', 'sdx-storage-'));
  process.env.SDX_CREDENTIAL_PATH = join(directory, 'credentials.json'); process.env.SDX_STATE_DIR = directory;
  try {
    await storeCredential('sk_stored_secret'); process.env.SUPERDOCS_API_KEY = 'sk_environment_secret';
    assert.equal((await resolveCredential()).source, 'environment');
    delete process.env.SUPERDOCS_API_KEY;
    await writeFile(join(directory, 'sessions.json'), '{bad');
    await assert.rejects(new SessionStore().list(), /corrupt/);
  } finally {
    delete process.env.SUPERDOCS_API_KEY; delete process.env.SDX_CREDENTIAL_PATH; delete process.env.SDX_STATE_DIR;
    await rm(directory, { recursive: true, force: true });
  }
});
