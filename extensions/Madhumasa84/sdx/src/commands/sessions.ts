import { SdxError } from '../api/errors.js';
import { baseEnvelope } from '../core/envelope.js';
import { EXIT_CODES } from '../core/exit-codes.js';
import type { OutputEnvelope } from '../core/output.js';
import type { SessionStore} from '../sessions/store.js';
import { validateAlias } from '../sessions/store.js';

export async function listSessions(store: SessionStore, startedAt = new Date()): Promise<OutputEnvelope> {
  const sessions = await store.list();
  return baseEnvelope('sessions list', startedAt, { data: { sessions } });
}

export async function showSession(store: SessionStore, name: string, startedAt = new Date()): Promise<OutputEnvelope> {
  validateAlias(name); const session = await store.get(name);
  if (!session) throw new SdxError(`Unknown session alias: ${name}`, EXIT_CODES.invalidInput);
  return baseEnvelope('sessions show', startedAt, { session: { id: session.serverSessionId, name }, data: { session } });
}

export async function removeSession(store: SessionStore, name: string, startedAt = new Date()): Promise<OutputEnvelope> {
  validateAlias(name); const removed = await store.remove(name);
  if (!removed) throw new SdxError(`Unknown session alias: ${name}`, EXIT_CODES.invalidInput);
  return baseEnvelope('sessions remove', startedAt, {
    warnings: ['Removed only the local alias. The remote SuperDocs File and session were not deleted or archived.'],
    data: { removed: name, remoteDeleted: false },
  });
}
