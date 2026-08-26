import { mkdir, readFile, writeFile } from "node:fs/promises";
import path from "node:path";
import { CONFIG } from "./config.js";
import type { Logger } from "./logger.js";
import type { AgentCredentials, AgentWhoamiResponse } from "./types.js";

async function fetchWhoami(apiKey: string): Promise<AgentWhoamiResponse | null> {
  const res = await fetch(`${CONFIG.API_BASE}/v1/agents/whoami`, {
    headers: { Authorization: `Bearer ${apiKey}` },
  });
  if (res.status === 401) return null;
  if (!res.ok) {
    throw new Error(`GET /v1/agents/whoami failed: ${res.status} ${res.statusText}`);
  }
  return (await res.json()) as AgentWhoamiResponse;
}

// endpoints/mcp_setup/handoff are fixed templates (verbatim from
// docs.superdocs.app/introduction/agent-signup), not account-specific data —
// safe to reconstruct here for a key that never went through our own signup.
function staticCredentialFields(
  apiKey: string,
): Pick<AgentCredentials, "endpoints" | "mcp_setup" | "handoff"> {
  return {
    endpoints: {
      mcp: `${CONFIG.API_BASE}/mcp/`,
      chat: `${CONFIG.API_BASE}/v1/chat`,
      whoami: `${CONFIG.API_BASE}/v1/agents/whoami`,
      openapi: `${CONFIG.API_BASE}/openapi.json`,
    },
    mcp_setup: {
      claude_code: `claude mcp add -s user --transport http superdocs ${CONFIG.API_BASE}/mcp/ --header "Authorization: Bearer ${apiKey}"`,
      generic_mcp: `Point any MCP client at ${CONFIG.API_BASE}/mcp/ (Streamable HTTP) with header Authorization: Bearer <your key>`,
      rest_fallback: `Prefer REST? POST ${CONFIG.API_BASE}/v1/chat with the Bearer header`,
      docs: "https://docs.superdocs.app/account/mcp-setup",
    },
    handoff: {
      how: "When you near the 500-op cap, POST /v1/agents/handoff with your key and {email}; you get back a short takeover code to give your human, who then adopts the account and can pay to continue",
    },
  };
}

/**
 * Reuse-first credential resolution, in order:
 *   1. SUPERDOCS_API_KEY env var, if set.
 *   2. CONFIG.CRED_PATH on disk, validated live via whoami.
 *   3. POST /v1/agents/signup, only if 1 and 2 both come up empty.
 * Step 3 must never run if step 2 succeeded — that's the whole point.
 */
export async function resolveCredentials(logger: Logger): Promise<AgentCredentials> {
  const envKey = process.env.SUPERDOCS_API_KEY;
  if (envKey) {
    logger.info("SUPERDOCS_API_KEY is set — using env key");
    const whoami = await fetchWhoami(envKey);
    if (!whoami) {
      throw new Error(
        "SUPERDOCS_API_KEY is set but GET /v1/agents/whoami rejected it (401). Fix or unset the env var — refusing to fall back to signup for an explicitly-provided key.",
      );
    }
    logger.success(
      `env key valid — account ${whoami.account_id}, tier ${whoami.quota.tier}, ${whoami.quota.remaining} ops remaining`,
    );
    return {
      account_id: whoami.account_id,
      slug: whoami.account_id,
      email: "",
      api_key: envKey,
      quota: whoami.quota,
      important:
        "Credentials resolved from SUPERDOCS_API_KEY; nothing was read from or written to CRED_PATH.",
      ...staticCredentialFields(envKey),
    };
  }

  try {
    const raw = await readFile(CONFIG.CRED_PATH, "utf8");
    const stored = JSON.parse(raw) as AgentCredentials;
    const whoami = await fetchWhoami(stored.api_key);
    if (whoami) {
      logger.success(
        `reusing stored credentials at ${CONFIG.CRED_PATH} — account ${stored.slug}, tier ${whoami.quota.tier}, ${whoami.quota.remaining} ops remaining`,
      );
      return { ...stored, quota: whoami.quota };
    }
    logger.warn(
      `stored key at ${CONFIG.CRED_PATH} was rejected (401) — the key is dead, not a downtime issue. Falling through to signup.`,
    );
  } catch (err) {
    if ((err as NodeJS.ErrnoException).code !== "ENOENT") throw err;
    logger.info(`no stored credentials at ${CONFIG.CRED_PATH}`);
  }

  logger.step("no reusable credentials — signing up for a new SuperDocs agent account");
  const res = await fetch(`${CONFIG.API_BASE}/v1/agents/signup`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      terms_accepted: true,
      agent_name: CONFIG.AGENT_NAME,
      operated_by_email: process.env.SUPERDOCS_OPERATOR_EMAIL,
      model_metadata: { built_by: "notesforge", runtime: process.version },
    }),
  });
  if (!res.ok) {
    throw new Error(`POST /v1/agents/signup failed: ${res.status} ${res.statusText}`);
  }
  const created = (await res.json()) as AgentCredentials;

  await mkdir(path.dirname(CONFIG.CRED_PATH), { recursive: true });
  await writeFile(CONFIG.CRED_PATH, JSON.stringify(created, null, 2), { mode: 0o600 });

  logger.success(
    `new agent account created — slug ${created.slug}, ${created.quota.remaining} ops remaining. Key saved to ${CONFIG.CRED_PATH} (shown once — do not lose it).`,
  );
  return created;
}
