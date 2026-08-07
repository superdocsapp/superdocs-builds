import type { RuntimeConfiguration } from '../config/store.js';
import { baseEnvelope } from '../core/envelope.js';
import type { OutputEnvelope } from '../core/output.js';
import { credentialPath, resolveCredential, storeCredential } from '../security/credentials.js';

export async function authLogin(readSecret: () => Promise<string>, startedAt = new Date()): Promise<OutputEnvelope> {
  const secret = await readSecret();
  await storeCredential(secret);
  return baseEnvelope('auth login', startedAt, { data: { stored: true, path: credentialPath() } });
}

export async function authStatus(configuration: RuntimeConfiguration, startedAt = new Date()): Promise<OutputEnvelope> {
  const credential = await resolveCredential();
  return baseEnvelope('auth status', startedAt, {
    data: {
      available: credential !== undefined,
      source: credential?.source ?? null,
      profile: configuration.profileName,
      apiBaseUrl: configuration.apiBaseUrl.toString(),
      maskedSuffix: credential ? `…${credential.apiKey.slice(-4)}` : null,
    },
  });
}
