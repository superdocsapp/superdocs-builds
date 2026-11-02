/** Documented SuperDocs MCP endpoint. Canonical trailing-slash form. */
export const DEFAULT_MCP_ENDPOINT = "https://api.superdocs.app/mcp/";

export const DEFAULT_TIMEOUT_MS = 60_000;
export const DEFAULT_SESSION_TTL_MS = 30 * 60 * 1000;
export const MAX_JSON_BODY_BYTES = 2_000_000;

export function readPositiveInt(value: string | undefined, fallback: number): number {
  if (!value) return fallback;
  const parsed = Number(value);
  if (!Number.isFinite(parsed) || parsed <= 0) return fallback;
  return parsed;
}
