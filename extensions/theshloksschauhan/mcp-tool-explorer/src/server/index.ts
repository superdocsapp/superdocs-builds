import path from "node:path";
import { fileURLToPath } from "node:url";
import { DEFAULT_MCP_ENDPOINT, readPositiveInt, DEFAULT_SESSION_TTL_MS, DEFAULT_TIMEOUT_MS } from "./config.js";
import { startApp } from "./http.js";

const host = process.env.SUPERDOCS_EXPLORER_HOST?.trim() || "127.0.0.1";
const port = readPositiveInt(process.env.SUPERDOCS_EXPLORER_PORT, 8787);
const endpoint = process.env.SUPERDOCS_MCP_URL?.trim() || DEFAULT_MCP_ENDPOINT;
const serverApiKey = process.env.SUPERDOCS_API_KEY?.trim() || undefined;
const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../..");

const running = await startApp({
  endpoint,
  serverApiKey,
  timeoutMs: readPositiveInt(process.env.SUPERDOCS_MCP_TIMEOUT_MS, DEFAULT_TIMEOUT_MS),
  sessionTtlMs: readPositiveInt(process.env.SUPERDOCS_SESSION_TTL_MS, DEFAULT_SESSION_TTL_MS),
  host,
  port,
  staticDir: path.join(root, "dist", "client"),
});

console.log(`SuperDocs MCP Tool Explorer listening on ${running.baseUrl}`);

async function shutdown(): Promise<void> {
  await running.close();
  process.exit(0);
}

process.on("SIGINT", () => {
  void shutdown();
});
process.on("SIGTERM", () => {
  void shutdown();
});
