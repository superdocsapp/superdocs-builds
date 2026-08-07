import { randomUUID } from 'node:crypto';
import { chmod, mkdir, readFile, rename, stat, writeFile } from 'node:fs/promises';
import { homedir } from 'node:os';
import { dirname, join } from 'node:path';

import { z } from 'zod';

import { SdxError } from '../api/errors.js';
import { ExportFormatSchema, type ExportFormat } from '../api/schemas.js';
import { EXIT_CODES } from '../core/exit-codes.js';
import { withFileLock } from '../storage/lock.js';

const ModelTierSchema = z.enum(['core', 'turbo', 'pro', 'max']);
const ColorPreferenceSchema = z.enum(['auto', 'always', 'never']);

const ProfileSettingsSchema = z
  .object({
    apiBaseUrl: z.string().url().optional(),
    modelTier: ModelTierSchema.optional(),
    exportFormat: ExportFormatSchema.optional(),
    timeoutSeconds: z.number().positive().optional(),
    pollIntervalMs: z.number().int().positive().optional(),
    color: ColorPreferenceSchema.optional(),
  })
  .strict();

const ProfileFileSchema = z
  .object({
    version: z.literal(1),
    activeProfile: z.string().min(1).optional(),
    profiles: z.record(z.string().min(1), ProfileSettingsSchema),
  })
  .strict();

export type ModelTier = z.infer<typeof ModelTierSchema>;
export type ColorPreference = z.infer<typeof ColorPreferenceSchema>;
export type ProfileSettings = z.infer<typeof ProfileSettingsSchema>;
export type ProfileFile = z.infer<typeof ProfileFileSchema>;

export interface RuntimeConfiguration {
  readonly profileName: string;
  readonly apiBaseUrl: URL;
  readonly modelTier: ModelTier;
  readonly exportFormat: ExportFormat;
  readonly timeoutSeconds: number;
  readonly pollIntervalMs: number;
  readonly color: ColorPreference;
}

export interface ConfigurationOverrides {
  readonly profile?: string;
  readonly apiBaseUrl?: string;
  readonly modelTier?: string;
  readonly exportFormat?: string;
  readonly timeoutSeconds?: number;
  readonly pollIntervalMs?: number;
  readonly color?: ColorPreference;
}

const BUILT_INS = {
  apiBaseUrl: 'https://api.superdocs.app',
  modelTier: 'core' as const,
  exportFormat: 'docx' as const,
  timeoutSeconds: 300,
  pollIntervalMs: 1000,
  color: 'auto' as const,
};

function configPath(): string {
  return process.env.SDX_CONFIG_PATH ?? join(homedir(), '.sdxrc');
}

async function atomicJson(path: string, value: unknown): Promise<void> {
  await mkdir(dirname(path), { recursive: true, mode: 0o700 });
  const temporary = `${path}.${process.pid}.${randomUUID()}.tmp`;
  try {
    await writeFile(temporary, `${JSON.stringify(value, null, 2)}\n`, {
      encoding: 'utf8',
      mode: 0o600,
      flag: 'wx',
    });
    await chmod(temporary, 0o600);
    await rename(temporary, path);
    await chmod(path, 0o600);
  } catch (error) {
    throw new SdxError(
      `Unable to write profile file ${path}.`,
      EXIT_CODES.invalidInput,
      undefined,
      { cause: error },
    );
  }
}

export class ProfileStore {
  public readonly path = configPath();

  public async read(): Promise<ProfileFile> {
    let raw: string;
    try {
      raw = await readFile(this.path, 'utf8');
    } catch (error) {
      if ((error as NodeJS.ErrnoException).code === 'ENOENT') {
        return { version: 1, activeProfile: 'default', profiles: {} };
      }
      throw new SdxError(
        `Unable to read profile file ${this.path}.`,
        EXIT_CODES.invalidInput,
        undefined,
        { cause: error },
      );
    }
    let candidate: unknown;
    try {
      candidate = JSON.parse(raw) as unknown;
    } catch (error) {
      throw new SdxError(
        `Profile file ${this.path} is not valid JSON.`,
        EXIT_CODES.invalidInput,
        undefined,
        { cause: error },
      );
    }
    const parsed = ProfileFileSchema.safeParse(candidate);
    if (!parsed.success) {
      const issue = parsed.error.issues[0];
      throw new SdxError(
        `Profile file ${this.path} is invalid${issue ? ` at ${issue.path.join('.') || '<root>'}: ${issue.message}` : '.'}`,
        EXIT_CODES.invalidInput,
      );
    }
    return parsed.data;
  }

  public async use(name: string): Promise<void> {
    await withFileLock(this.path, async () => {
      const file = await this.read();
      if (name !== 'default' && file.profiles[name] === undefined) {
        throw new SdxError(`Unknown profile: ${name}`, EXIT_CODES.invalidInput);
      }
      await atomicJson(this.path, { ...file, activeProfile: name });
    });
  }

  public async permissions(): Promise<number | null> {
    try {
      return (await stat(this.path)).mode & 0o777;
    } catch (error) {
      if ((error as NodeJS.ErrnoException).code === 'ENOENT') return null;
      throw error;
    }
  }
}

function parseEnvironment(): ProfileSettings & { profile?: string } {
  const candidate: Record<string, unknown> = {};
  if (process.env.SDX_API_BASE_URL) candidate.apiBaseUrl = process.env.SDX_API_BASE_URL;
  if (process.env.SDX_MODEL_TIER) candidate.modelTier = process.env.SDX_MODEL_TIER;
  if (process.env.SDX_EXPORT_FORMAT) candidate.exportFormat = process.env.SDX_EXPORT_FORMAT;
  if (process.env.SDX_TIMEOUT) candidate.timeoutSeconds = Number(process.env.SDX_TIMEOUT);
  if (process.env.SDX_POLL_INTERVAL) candidate.pollIntervalMs = Number(process.env.SDX_POLL_INTERVAL);
  if (process.env.SDX_COLOR) candidate.color = process.env.SDX_COLOR;
  const parsed = ProfileSettingsSchema.safeParse(candidate);
  if (!parsed.success) {
    throw new SdxError(
      `Invalid SDX environment configuration: ${parsed.error.issues[0]?.message ?? 'unknown value'}`,
      EXIT_CODES.invalidInput,
    );
  }
  return { ...parsed.data, ...(process.env.SDX_PROFILE ? { profile: process.env.SDX_PROFILE } : {}) };
}

export async function resolveConfiguration(
  store: ProfileStore,
  cli: ConfigurationOverrides,
): Promise<RuntimeConfiguration> {
  const file = await store.read();
  const environment = parseEnvironment();
  const profileName = cli.profile ?? environment.profile ?? file.activeProfile ?? 'default';
  const selected = profileName === 'default' ? undefined : file.profiles[profileName];
  if (profileName !== 'default' && selected === undefined) {
    throw new SdxError(`Unknown profile: ${profileName}`, EXIT_CODES.invalidInput);
  }
  const defaults = file.profiles.default;
  const apiBaseUrlValue = cli.apiBaseUrl ?? environment.apiBaseUrl ?? selected?.apiBaseUrl ?? defaults?.apiBaseUrl ?? BUILT_INS.apiBaseUrl;
  const modelTierValue = cli.modelTier ?? environment.modelTier ?? selected?.modelTier ?? defaults?.modelTier ?? BUILT_INS.modelTier;
  const exportFormatValue = cli.exportFormat ?? environment.exportFormat ?? selected?.exportFormat ?? defaults?.exportFormat ?? BUILT_INS.exportFormat;
  const timeoutSeconds = cli.timeoutSeconds ?? environment.timeoutSeconds ?? selected?.timeoutSeconds ?? defaults?.timeoutSeconds ?? BUILT_INS.timeoutSeconds;
  const pollIntervalMs = cli.pollIntervalMs ?? environment.pollIntervalMs ?? selected?.pollIntervalMs ?? defaults?.pollIntervalMs ?? BUILT_INS.pollIntervalMs;
  const color = cli.color ?? environment.color ?? selected?.color ?? defaults?.color ?? BUILT_INS.color;
  const modelTier = ModelTierSchema.safeParse(modelTierValue);
  const exportFormat = ExportFormatSchema.safeParse(exportFormatValue);
  if (!modelTier.success || !exportFormat.success) {
    throw new SdxError('Invalid model tier or export format.', EXIT_CODES.invalidInput);
  }
  let apiBaseUrl: URL;
  try {
    apiBaseUrl = new URL(apiBaseUrlValue);
    if (!['http:', 'https:'].includes(apiBaseUrl.protocol)) throw new Error('unsupported protocol');
  } catch (error) {
    throw new SdxError('API base URL must be a valid HTTP(S) URL.', EXIT_CODES.invalidInput, undefined, { cause: error });
  }
  return {
    profileName,
    apiBaseUrl,
    modelTier: modelTier.data,
    exportFormat: exportFormat.data,
    timeoutSeconds: timeoutSeconds,
    pollIntervalMs: pollIntervalMs,
    color: color,
  };
}
