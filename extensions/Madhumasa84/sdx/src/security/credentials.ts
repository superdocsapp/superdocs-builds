import { randomUUID } from 'node:crypto';
import { chmod, mkdir, readFile, rename, stat, writeFile } from 'node:fs/promises';
import { homedir } from 'node:os';
import { dirname, join } from 'node:path';

import { z } from 'zod';

import { SdxError } from '../api/errors.js';
import { EXIT_CODES } from '../core/exit-codes.js';
import { withFileLock } from '../storage/lock.js';

const CredentialFileSchema = z
  .object({ version: z.literal(1), apiKey: z.string().min(8) })
  .strict();

export interface ResolvedCredential {
  readonly apiKey: string;
  readonly source: 'environment' | 'stored';
}

export function credentialPath(): string {
  return process.env.SDX_CREDENTIAL_PATH ?? join(homedir(), '.sdx', 'credentials.json');
}

export async function storeCredential(apiKey: string): Promise<void> {
  const trimmed = apiKey.trim();
  if (trimmed.length < 8 || /\s/.test(trimmed)) {
    throw new SdxError('The API key is not in a valid form.', EXIT_CODES.invalidInput);
  }
  const path = credentialPath();
  await withFileLock(path, async () => {
    await mkdir(dirname(path), { recursive: true, mode: 0o700 });
    await chmod(dirname(path), 0o700);
    const temporary = `${path}.${process.pid}.${randomUUID()}.tmp`;
    try {
      await writeFile(temporary, `${JSON.stringify({ version: 1, apiKey: trimmed })}\n`, {
        encoding: 'utf8', mode: 0o600, flag: 'wx',
      });
      await chmod(temporary, 0o600); await rename(temporary, path); await chmod(path, 0o600);
    } catch (error) {
      throw new SdxError('Unable to store credentials securely.', EXIT_CODES.invalidInput, undefined, { cause: error });
    }
  });
}

export async function readStoredCredential(): Promise<string | undefined> {
  const path = credentialPath();
  let raw: string;
  try {
    raw = await readFile(path, 'utf8');
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code === 'ENOENT') return undefined;
    throw new SdxError('Unable to read stored credentials.', EXIT_CODES.authenticationFailure, undefined, { cause: error });
  }
  let candidate: unknown;
  try {
    candidate = JSON.parse(raw) as unknown;
  } catch (error) {
    throw new SdxError('Stored credential file is corrupt; run `sdx auth login` to replace it.', EXIT_CODES.authenticationFailure, undefined, { cause: error });
  }
  const parsed = CredentialFileSchema.safeParse(candidate);
  if (!parsed.success) {
    throw new SdxError('Stored credential file is invalid; run `sdx auth login` to replace it.', EXIT_CODES.authenticationFailure);
  }
  return parsed.data.apiKey;
}

export async function resolveCredential(): Promise<ResolvedCredential | undefined> {
  const environment = process.env.SUPERDOCS_API_KEY?.trim();
  if (environment) return { apiKey: environment, source: 'environment' };
  const stored = await readStoredCredential();
  return stored ? { apiKey: stored, source: 'stored' } : undefined;
}

export async function credentialPermissions(): Promise<number | null> {
  try {
    return (await stat(credentialPath())).mode & 0o777;
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code === 'ENOENT') return null;
    throw error;
  }
}

export async function readHiddenCredential(): Promise<string> {
  if (!process.stdin.isTTY || typeof process.stdin.setRawMode !== 'function') {
    let value = '';
    process.stderr.write('SuperDocs API key: ');
    process.stdin.setEncoding('utf8');
    for await (const chunk of process.stdin) value += chunk;
    process.stderr.write('\n');
    return value.split(/\r?\n/, 1)[0] ?? '';
  }

  const input = process.stdin;
  const output = process.stderr;
  output.write('SuperDocs API key: ');
  input.setRawMode(true);
  input.resume();
  input.setEncoding('utf8');
  try {
    return await new Promise<string>((resolve, reject) => {
      let value = '';
      const onData = (chunk: string | Buffer): void => {
        const text = String(chunk);
        for (const character of text) {
          if (character === '\u0003') {
            cleanup();
            reject(new SdxError('Operation interrupted by the user.', EXIT_CODES.interrupted));
            return;
          }
          if (character === '\r' || character === '\n') {
            cleanup();
            output.write('\n');
            resolve(value);
            return;
          }
          if (character === '\u007f' || character === '\b') value = value.slice(0, -1);
          else if (character >= ' ') value += character;
        }
      };
      const cleanup = (): void => { input.removeListener('data', onData); };
      input.on('data', onData);
    });
  } finally {
    input.setRawMode(false);
    input.pause();
  }
}
