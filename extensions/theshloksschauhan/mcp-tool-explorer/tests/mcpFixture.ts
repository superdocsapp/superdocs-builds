import { createServer, type Server } from "node:http";
import type { AddressInfo } from "node:net";

export type FixtureTool = {
  name: string;
  description?: string;
  inputSchema: Record<string, unknown>;
};

type JsonRpc = {
  jsonrpc?: string;
  id?: number | string;
  method?: string;
  params?: Record<string, unknown>;
};

export type FixtureOptions = {
  apiKey: string;
  tools: FixtureTool[];
  pageSize?: number;
  callDelayMs?: number;
  failAuth?: boolean;
  dropSession?: boolean;
  toolError?: boolean;
  protocolError?: string;
};

export type Fixture = {
  url: string;
  calls: Array<{ name: string; arguments: unknown }>;
  sessionHeaders: string[];
  close: () => Promise<void>;
};

export async function startFixture(options: FixtureOptions): Promise<Fixture> {
  const calls: Array<{ name: string; arguments: unknown }> = [];
  const sessionHeaders: string[] = [];
  const sessionId = "fixture-session";

  const server: Server = createServer(async (req, res) => {
    if (req.method === "GET") {
      res.writeHead(405, { allow: "POST, DELETE" });
      res.end();
      return;
    }
    if (req.method === "DELETE") {
      res.writeHead(200).end();
      return;
    }
    const header = req.headers.authorization;
    if (options.failAuth || header !== `Bearer ${options.apiKey}`) {
      res.writeHead(401, { "content-type": "application/json" });
      res.end(JSON.stringify({ detail: "Authentication required. Provide an sk_ or lce_ API key as Bearer token." }));
      return;
    }

    const chunks: Buffer[] = [];
    for await (const chunk of req) chunks.push(Buffer.isBuffer(chunk) ? chunk : Buffer.from(chunk));
    const raw = Buffer.concat(chunks).toString("utf8");
    let message: JsonRpc;
    try {
      message = raw ? (JSON.parse(raw) as JsonRpc) : {};
    } catch {
      res.writeHead(400).end();
      return;
    }

    if (message.id !== undefined && message.method !== "initialize") {
      const seen = req.headers["mcp-session-id"];
      const value = Array.isArray(seen) ? seen[0] : seen;
      if (value) sessionHeaders.push(value);
      if (options.dropSession || value !== sessionId) {
        res.writeHead(404, { "content-type": "application/json" });
        res.end(JSON.stringify({ detail: "Session not found" }));
        return;
      }
    }

    if (!message.method || message.id === undefined) {
      res.writeHead(202).end();
      return;
    }

    const result = await responseFor(message, options, calls);
    if (message.method === "initialize") res.setHeader("mcp-session-id", sessionId);
    res.writeHead(200, { "content-type": "application/json" });
    res.end(JSON.stringify({ jsonrpc: "2.0", id: message.id, ...result }));
  });

  await new Promise<void>((resolve) => server.listen(0, "127.0.0.1", () => resolve()));
  const address = server.address() as AddressInfo;
  return {
    url: `http://127.0.0.1:${address.port}/mcp/`,
    calls,
    sessionHeaders,
    close: () => new Promise((resolve, reject) => server.close((error) => (error ? reject(error) : resolve()))),
  };
}

async function responseFor(
  message: JsonRpc,
  options: FixtureOptions,
  calls: Array<{ name: string; arguments: unknown }>,
): Promise<{ result?: unknown; error?: { code: number; message: string } }> {
  if (message.method === "initialize") {
    const protocolVersion =
      typeof message.params?.protocolVersion === "string" ? message.params.protocolVersion : "2025-03-26";
    return {
      result: {
        protocolVersion,
        capabilities: { tools: { listChanged: false } },
        serverInfo: { name: "fixture-superdocs", version: "0.0.0" },
        instructions: "Fixture instructions.",
      },
    };
  }
  if (message.method === "tools/list") {
    const pageSize = options.pageSize ?? options.tools.length;
    const cursor = typeof message.params?.cursor === "string" ? Number(message.params.cursor) : 0;
    const slice = options.tools.slice(cursor, cursor + pageSize);
    const next = cursor + pageSize;
    return {
      result: {
        tools: slice,
        nextCursor: next < options.tools.length ? String(next) : undefined,
      },
    };
  }
  if (message.method === "tools/call") {
    const name = typeof message.params?.name === "string" ? message.params.name : "";
    const args = message.params?.arguments ?? {};
    calls.push({ name, arguments: args });
    if (options.callDelayMs) await new Promise((resolve) => setTimeout(resolve, options.callDelayMs));
    if (options.protocolError) return { error: { code: -32602, message: options.protocolError } };
    return {
      result: {
        content: [{ type: "text", text: JSON.stringify({ name, arguments: args }) }],
        structuredContent: { name, arguments: args },
        isError: options.toolError === true,
      },
    };
  }
  if (message.method === "ping") return { result: {} };
  return { error: { code: -32601, message: `Unknown method ${message.method}` } };
}
