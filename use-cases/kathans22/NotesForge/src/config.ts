import os from "node:os";
import path from "node:path";

export const CONFIG = Object.freeze({
  API_BASE: "https://api.superdocs.app",
  MCP_URL: "https://api.superdocs.app/mcp",
  CRED_PATH: path.join(os.homedir(), ".superdocs", "agent_credentials.json"),
  OPS_CAP: 25,
  POLL_INTERVAL_MS: 2000,
  POLL_TIMEOUT_MS: 600_000,
  INLINE_UPLOAD_MAX_BYTES: 100 * 1024,
  AGENT_NAME: "notesforge",
});
