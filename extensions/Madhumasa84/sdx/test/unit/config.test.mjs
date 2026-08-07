import assert from 'node:assert/strict';
import { mkdtemp, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import test from 'node:test';

import { ProfileStore, resolveConfiguration } from '../../dist/config/store.js';

async function withConfig(body, callback) {
  const directory = await mkdtemp(join(tmpdir(), 'sdx-config-'));
  const path = join(directory, '.sdxrc');
  const prior = process.env.SDX_CONFIG_PATH;
  process.env.SDX_CONFIG_PATH = path;
  if (body !== undefined) await writeFile(path, typeof body === 'string' ? body : JSON.stringify(body));
  try { return await callback(new ProfileStore()); }
  finally { if (prior === undefined) delete process.env.SDX_CONFIG_PATH; else process.env.SDX_CONFIG_PATH = prior; await rm(directory, { recursive: true, force: true }); }
}

test('configuration precedence is CLI > environment > selected > default > built-in', async () => {
  await withConfig({ version: 1, activeProfile: 'work', profiles: {
    default: { exportFormat: 'pdf', timeoutSeconds: 30, pollIntervalMs: 900 },
    work: { exportFormat: 'html', timeoutSeconds: 20 },
  } }, async (store) => {
    process.env.SDX_EXPORT_FORMAT = 'txt';
    try {
      const resolved = await resolveConfiguration(store, { exportFormat: 'markdown' });
      assert.equal(resolved.exportFormat, 'markdown');
      assert.equal(resolved.timeoutSeconds, 20);
      assert.equal(resolved.pollIntervalMs, 900);
      assert.equal(resolved.modelTier, 'core');
    } finally { delete process.env.SDX_EXPORT_FORMAT; }
  });
});

test('unknown profile and malformed/unknown fields fail explicitly', async () => {
  await withConfig({ version: 1, profiles: {} }, async (store) => {
    await assert.rejects(resolveConfiguration(store, { profile: 'missing' }), /Unknown profile/);
  });
  await withConfig({ version: 1, profiles: { default: { apiBasUrl: 'https://typo.invalid' } } }, async (store) => {
    await assert.rejects(store.read(), /Unrecognized key/);
  });
  await withConfig('{bad', async (store) => {
    await assert.rejects(store.read(), /not valid JSON/);
  });
});
