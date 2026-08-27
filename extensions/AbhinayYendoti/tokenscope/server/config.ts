import { TokenScopeError } from "./errors.js";

/**
 * Configuration, and the only place the API key is read.
 *
 * The key lives in this process and is never serialised into a response, a log
 * line or the client bundle. `describe()` exists so the rest of the server can
 * talk about the configuration without being handed the secret.
 */

export type ModelTier = "core" | "turbo" | "pro" | "max";

const TIERS: readonly ModelTier[] = ["core", "turbo", "pro", "max"];

export interface Config {
  baseUrl: string;
  modelTier: ModelTier;
  port: number;
  configured: boolean;
}

let apiKey = "";
let config: Config = {
  baseUrl: "https://api.superdocs.app/v1",
  modelTier: "core",
  port: 8787,
  configured: false
};

export function loadConfig(env: NodeJS.ProcessEnv = process.env): Config {
  apiKey = (env["SUPERDOCS_API_KEY"] ?? "").trim();

  const tier = (env["SUPERDOCS_MODEL_TIER"] ?? "core").trim() as ModelTier;
  const port = Number.parseInt(env["PORT"] ?? "8787", 10);

  config = {
    baseUrl: (env["SUPERDOCS_BASE_URL"] ?? "https://api.superdocs.app/v1").replace(/\/+$/u, ""),
    modelTier: TIERS.includes(tier) ? tier : "core",
    port: Number.isFinite(port) ? port : 8787,
    configured: apiKey.length > 0
  };

  return config;
}

export function getConfig(): Config {
  return config;
}

/** Throws the error the pane knows how to render when the key is absent. */
export function requireApiKey(): string {
  if (apiKey.length === 0) {
    throw new TokenScopeError(
      "no_api_key",
      "SUPERDOCS_API_KEY is not set, so TokenScope cannot reach SuperDocs.",
      { hint: "Copy .env.example to .env.local, add your key, and restart the server." }
    );
  }

  return apiKey;
}
