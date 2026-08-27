import { mkdir, readdir, readFile } from 'node:fs/promises';
import { dirname, join } from 'node:path';
import { randomBytes } from 'node:crypto';
import { atomicWrite, ensurePrivateDir } from './io.js';
import { validateManifest } from './schema.js';
import { ChangelogError } from './errors.js';

export function makeRunId() {
  return `run_${Date.now().toString(36)}_${randomBytes(6).toString('hex')}`;
}

export async function defaultStateDir(canonicalPath) {
  const path = join(dirname(canonicalPath), '.changelog-maintainer');
  await ensurePrivateDir(path);
  return path;
}

export function statePath(stateDir, runId) {
  return join(stateDir, `${runId}.json`);
}

export async function saveManifest(stateDir, manifest) {
  await ensurePrivateDir(stateDir);
  await atomicWrite(statePath(stateDir, manifest.run_id), `${JSON.stringify(manifest, null, 2)}\n`, { mode: 0o600 });
}

export async function loadManifest(stateDir, runId) {
  try { return validateManifest(JSON.parse(await readFile(statePath(stateDir, runId), 'utf8'))); }
  catch (error) {
    if (error?.code === 'ENOENT') throw new ChangelogError(`unknown changelog run: ${runId}`, 'UNKNOWN_RUN', 11);
    if (error instanceof ChangelogError) throw error;
    throw new ChangelogError(`corrupt changelog state for ${runId}`, 'CORRUPT_STATE', 11);
  }
}

export async function listManifests(stateDir) {
  try {
    const names = (await readdir(stateDir)).filter((name) => name.endsWith('.json'));
    return Promise.all(names.map(async (name) => {
      try { return validateManifest(JSON.parse(await readFile(join(stateDir, name), 'utf8'))); } catch { return null; }
    })).then((items) => items.filter(Boolean));
  } catch (error) {
    if (error?.code === 'ENOENT') return [];
    throw error;
  }
}

export async function checkpoint(stateDir, manifest, name, patch = {}, failAt) {
  const next = { ...manifest, ...patch, checkpoints: [...new Set([...(manifest.checkpoints || []), name])], updated_at: new Date().toISOString() };
  await saveManifest(stateDir, next);
  if (failAt === name) throw new (await import('./errors.js')).InjectedFailure(name);
  return next;
}
