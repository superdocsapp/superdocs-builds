import { SdxError } from '../api/errors.js';
import type { ProfileStore } from '../config/store.js';
import { baseEnvelope } from '../core/envelope.js';
import { EXIT_CODES } from '../core/exit-codes.js';
import type { OutputEnvelope } from '../core/output.js';
import { validateAlias } from '../sessions/store.js';

export async function listProfiles(store: ProfileStore, startedAt = new Date()): Promise<OutputEnvelope> {
  const file = await store.read();
  const names = [...new Set(['default', ...Object.keys(file.profiles)])].sort();
  return baseEnvelope('profiles list', startedAt, { data: { activeProfile: file.activeProfile ?? 'default', profiles: names } });
}

export async function showProfile(store: ProfileStore, name: string, startedAt = new Date()): Promise<OutputEnvelope> {
  validateAlias(name); const file = await store.read();
  if (name !== 'default' && file.profiles[name] === undefined) throw new SdxError(`Unknown profile: ${name}`, EXIT_CODES.invalidInput);
  return baseEnvelope('profiles show', startedAt, { data: { name, active: (file.activeProfile ?? 'default') === name, settings: file.profiles[name] ?? {} } });
}

export async function useProfile(store: ProfileStore, name: string, startedAt = new Date()): Promise<OutputEnvelope> {
  validateAlias(name); await store.use(name);
  return baseEnvelope('profiles use', startedAt, { data: { activeProfile: name } });
}
