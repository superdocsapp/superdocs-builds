/**
 * Boot configuration, validated once.
 *
 * Anything that can be wrong about the environment is wrong here, at startup,
 * with a message naming the variable — not four layers deep in a request when a
 * fetch to `undefined/api/now/table/...` returns something unhelpful.
 */

const DEFAULTS = {
  port: 8787,
  superDocsBaseUrl: "https://api.superdocs.app",
  runTtlMs: 60 * 60 * 1000,
  runLimit: 200,
  healthCacheMs: 15_000,
  quotaCacheMs: 60_000
};

/** Parsers that keep "" and undefined distinguishable from a real value. */
function str(value, fallback = "") {
  const trimmed = String(value ?? "").trim();
  return trimmed || fallback;
}

function bool(value, fallback = false) {
  const trimmed = String(value ?? "").trim().toLowerCase();
  if (!trimmed) return fallback;
  return trimmed === "true" || trimmed === "1" || trimmed === "yes";
}

function int(value, fallback) {
  const parsed = Number.parseInt(String(value ?? "").trim(), 10);
  return Number.isFinite(parsed) ? parsed : fallback;
}

function num(value, fallback) {
  const parsed = Number.parseFloat(String(value ?? "").trim());
  return Number.isFinite(parsed) ? parsed : fallback;
}

export class ConfigError extends Error {
  constructor(problems) {
    super(`Configuration is invalid:\n  - ${problems.join("\n  - ")}`);
    this.name = "ConfigError";
    this.problems = problems;
  }
}

/**
 * ServiceNow is reached over HTTP either way. `mock` points the same client at
 * this process's own Table API; `live` points it at a real instance. The rest of
 * the app cannot tell the difference, which is the entire point of the seam.
 */
export function loadConfig(env = process.env) {
  const problems = [];

  const port = int(env.PORT, DEFAULTS.port);
  if (port < 1 || port > 65_535) problems.push(`PORT must be 1-65535, got "${env.PORT}".`);

  const superDocsApiKey = str(env.SUPERDOCS_API_KEY);
  const superDocsBaseUrl = str(env.SUPERDOCS_BASE_URL, DEFAULTS.superDocsBaseUrl).replace(/\/+$/u, "");

  if (superDocsApiKey && !/^(sk_|lce_)/u.test(superDocsApiKey)) {
    problems.push('SUPERDOCS_API_KEY does not look like a SuperDocs key (expected an "sk_" prefix).');
  }

  const replayMode = str(env.SUPERDOCS_REPLAY, "off").toLowerCase();
  if (!["off", "record", "replay"].includes(replayMode)) {
    problems.push(`SUPERDOCS_REPLAY must be off, record or replay, got "${replayMode}".`);
  }

  const serviceNowLive = bool(env.SERVICENOW_ENABLED, false);
  const serviceNow = serviceNowLive
    ? {
        mode: "live",
        instanceUrl: str(env.SERVICENOW_INSTANCE_URL).replace(/\/+$/u, ""),
        username: str(env.SERVICENOW_USERNAME),
        password: str(env.SERVICENOW_PASSWORD)
      }
    : {
        mode: "mock",
        instanceUrl: `http://127.0.0.1:${port}/mock/servicenow`,
        username: str(env.SERVICENOW_MOCK_USERNAME, "svcflow.integration"),
        password: str(env.SERVICENOW_MOCK_PASSWORD, "mock-instance-secret"),
        latencyMs: Math.max(0, int(env.SERVICENOW_MOCK_LATENCY_MS, 60)),
        failureRate: Math.min(1, Math.max(0, num(env.SERVICENOW_MOCK_FAILURE_RATE, 0)))
      };

  if (serviceNowLive) {
    for (const [key, value] of [
      ["SERVICENOW_INSTANCE_URL", serviceNow.instanceUrl],
      ["SERVICENOW_USERNAME", serviceNow.username],
      ["SERVICENOW_PASSWORD", serviceNow.password]
    ]) {
      if (!value) problems.push(`SERVICENOW_ENABLED=true requires ${key}.`);
    }

    if (serviceNow.instanceUrl && !/^https?:\/\//u.test(serviceNow.instanceUrl)) {
      problems.push("SERVICENOW_INSTANCE_URL must start with http:// or https://.");
    }
  }

  if (problems.length) throw new ConfigError(problems);

  return {
    port,
    env: str(env.NODE_ENV, "development"),
    logLevel: str(env.LOG_LEVEL, "info"),
    superDocs: {
      apiKey: superDocsApiKey,
      baseUrl: superDocsBaseUrl,
      configured: Boolean(superDocsApiKey),
      replayMode,
      cassetteDir: str(env.SUPERDOCS_CASSETTE_DIR, "server/cassettes")
    },
    serviceNow,
    writeBack: bool(env.SERVICENOW_WRITE_BACK, true),
    runTtlMs: int(env.RUN_TTL_MS, DEFAULTS.runTtlMs),
    runLimit: int(env.RUN_LIMIT, DEFAULTS.runLimit),
    runStatePath: str(env.RUN_STATE_PATH, ".runs"),
    healthCacheMs: DEFAULTS.healthCacheMs,
    quotaCacheMs: DEFAULTS.quotaCacheMs
  };
}

/** Never log the whole config: it carries the API key and the instance password. */
export function describeConfig(config) {
  return {
    env: config.env,
    port: config.port,
    serviceNow: { mode: config.serviceNow.mode, instanceUrl: config.serviceNow.instanceUrl },
    superDocs: {
      baseUrl: config.superDocs.baseUrl,
      configured: config.superDocs.configured,
      replayMode: config.superDocs.replayMode
    },
    writeBack: config.writeBack
  };
}
