export interface AegisConfig {
  mode: 'mock' | 'live';
  retryBudget: number;
  timeoutMs: number;
  logLevel: 'debug' | 'info' | 'warn' | 'error';
  logDocumentContent: boolean;
}

const LOG_LEVELS = new Set(['debug', 'info', 'warn', 'error']);

/**
 * Reads AEGIS_* variables from `env` (defaults to `process.env`) with safe
 * fallbacks. Never reads or returns a credential — SUPERDOC_HOST_TOKEN and
 * ANTHROPIC_API_KEY are read directly by the adapters that need them (none,
 * in this repository's mock-only configuration), never copied into this
 * shared config object, so they can't accidentally leak into a log line or
 * an EditProof by being present on a config object that gets serialized.
 */
export function loadConfig(env: NodeJS.ProcessEnv = process.env): AegisConfig {
  return {
    mode: env.AEGIS_MODE === 'live' ? 'live' : 'mock',
    retryBudget: parsePositiveInt(env.AEGIS_RETRY_BUDGET, 2),
    timeoutMs: parsePositiveInt(env.AEGIS_TIMEOUT_MS, 10_000),
    logLevel: (LOG_LEVELS.has(env.AEGIS_LOG_LEVEL ?? '') ? env.AEGIS_LOG_LEVEL : 'info') as AegisConfig['logLevel'],
    logDocumentContent: env.AEGIS_LOG_DOCUMENT_CONTENT === 'true',
  };
}

function parsePositiveInt(value: string | undefined, fallback: number): number {
  const parsed = Number(value);
  return Number.isFinite(parsed) && parsed > 0 ? Math.floor(parsed) : fallback;
}
