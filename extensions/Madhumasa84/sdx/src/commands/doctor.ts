import { link, mkdtemp, rename, rm, stat, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { dirname, join } from 'node:path';

import type { RuntimeConfiguration } from '../config/store.js';
import type { ProfileStore } from '../config/store.js';
import { baseEnvelope } from '../core/envelope.js';
import type { OutputEnvelope } from '../core/output.js';
import type { OperationLedger } from '../operations/ledger.js';
import { credentialPermissions, resolveCredential } from '../security/credentials.js';
import type { PendingJobStore, SessionStore } from '../sessions/store.js';

export interface Diagnostic { readonly name: string; readonly status: 'pass' | 'warn' | 'fail'; readonly message: string; }

function permissionDiagnostic(name: string, mode: number | null): Diagnostic {
  if (mode === null) return { name, status: 'pass', message: 'File does not exist yet.' };
  return mode & 0o077 ? { name, status: 'fail', message: `Permissions ${mode.toString(8)} are too broad; use 600.` } : { name, status: 'pass', message: `Permissions ${mode.toString(8)} are restrictive.` };
}

async function directoryPermissionDiagnostic(path: string): Promise<Diagnostic> {
  try {
    const mode = (await stat(path)).mode & 0o777;
    return mode & 0o077
      ? { name: 'state-directory-permissions', status: 'fail', message: `Permissions ${mode.toString(8)} are too broad; use 700.` }
      : { name: 'state-directory-permissions', status: 'pass', message: `Permissions ${mode.toString(8)} are restrictive.` };
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code === 'ENOENT') return { name: 'state-directory-permissions', status: 'pass', message: 'State directory does not exist yet.' };
    return { name: 'state-directory-permissions', status: 'fail', message: 'Unable to inspect the state directory.' };
  }
}

export async function doctor(
  configuration: RuntimeConfiguration, profiles: ProfileStore, sessions: SessionStore,
  jobs: PendingJobStore, ledger: OperationLedger, startedAt = new Date(),
): Promise<OutputEnvelope> {
  const diagnostics: Diagnostic[] = [];
  const major = Number(process.versions.node.split('.')[0]);
  diagnostics.push(major >= 20 ? { name: 'node', status: 'pass', message: `Node ${process.versions.node} satisfies >=20.` } : { name: 'node', status: 'fail', message: `Node ${process.versions.node} is unsupported; install Node 20+.` });
  try { await profiles.read(); diagnostics.push({ name: 'profiles', status: 'pass', message: `Profile ${configuration.profileName} parsed successfully.` }); }
  catch (error) { diagnostics.push({ name: 'profiles', status: 'fail', message: error instanceof Error ? error.message : 'Profile parsing failed.' }); }
  const credential = await resolveCredential().catch(() => undefined);
  diagnostics.push(credential ? { name: 'credentials', status: 'pass', message: `Credential available from ${credential.source}.` } : { name: 'credentials', status: 'warn', message: 'No credential available; run `sdx auth login` or set SUPERDOCS_API_KEY.' });
  diagnostics.push(permissionDiagnostic('credential-permissions', await credentialPermissions()));
  diagnostics.push(permissionDiagnostic('session-permissions', await sessions.permissions()));
  diagnostics.push(permissionDiagnostic('pending-job-permissions', await jobs.permissions()));
  diagnostics.push(permissionDiagnostic('operation-ledger-permissions', await ledger.permissions()));
  diagnostics.push(permissionDiagnostic('profile-permissions', await profiles.permissions()));
  diagnostics.push(await directoryPermissionDiagnostic(dirname(sessions.path)));
  diagnostics.push({ name: 'api-base-url', status: ['http:', 'https:'].includes(configuration.apiBaseUrl.protocol) ? 'pass' : 'fail', message: `API endpoint is ${configuration.apiBaseUrl.origin}.` });
  let directory: string | undefined;
  try {
    directory = await mkdtemp(join(tmpdir(), 'sdx-doctor-'));
    const first = join(directory, 'first'); const second = join(directory, 'second'); const third = join(directory, 'third');
    await writeFile(first, 'probe', { flag: 'wx', mode: 0o600 }); await link(first, second); await rename(second, third);
    diagnostics.push({ name: 'filesystem', status: 'pass', message: 'Temporary writes, exclusive links, and atomic rename are available.' });
  } catch (error) {
    diagnostics.push({ name: 'filesystem', status: 'fail', message: `Required filesystem capabilities failed: ${error instanceof Error ? error.message : String(error)}` });
  } finally { if (directory) await rm(directory, { recursive: true, force: true }); }
  const failed = diagnostics.some((item) => item.status === 'fail');
  return baseEnvelope('doctor', startedAt, { status: failed ? 'failed' : 'completed', ok: !failed, diagnostics });
}
