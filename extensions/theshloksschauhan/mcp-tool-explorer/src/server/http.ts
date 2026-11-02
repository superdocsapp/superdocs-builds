import { createServer, type IncomingMessage, type Server, type ServerResponse } from "node:http";
import { randomUUID } from "node:crypto";
import { createReadStream } from "node:fs";
import { stat } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { redactSecrets } from "../shared/redact.js";
import { validateToolArguments } from "../shared/schema.js";
import type { ErrorPayload, JsonSchema, PublicConfig, ToolCallPayload, ToolDescriptor } from "../shared/types.js";
import { DEFAULT_SESSION_TTL_MS, DEFAULT_TIMEOUT_MS, MAX_JSON_BODY_BYTES } from "./config.js";
import { ExplorerError } from "./errors.js";
import { connectSuperdocs, type McpConnection } from "./mcpClient.js";

type ConnectFn = typeof connectSuperdocs;

type SessionRecord = {
  id: string;
  connection: McpConnection;
  tools: ToolDescriptor[] | null;
  secret: string;
  lastUsed: number;
  tail: Promise<void>;
};

export type AppOptions = {
  endpoint: string;
  serverApiKey?: string;
  timeoutMs?: number;
  sessionTtlMs?: number;
  host?: string;
  port?: number;
  staticDir?: string;
  connect?: ConnectFn;
};

export type RunningApp = {
  baseUrl: string;
  close: () => Promise<void>;
};

const MIME: Record<string, string> = {
  ".html": "text/html; charset=utf-8",
  ".js": "text/javascript; charset=utf-8",
  ".css": "text/css; charset=utf-8",
  ".svg": "image/svg+xml",
  ".json": "application/json; charset=utf-8",
  ".map": "application/json; charset=utf-8",
  ".png": "image/png",
  ".webp": "image/webp",
  ".ico": "image/x-icon",
};

function projectRoot(): string {
  return path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../..");
}

function sendJson(res: ServerResponse, status: number, body: unknown, secret?: string): void {
  const safe = secret ? redactSecrets(body, [secret]) : redactSecrets(body);
  const payload = JSON.stringify(safe);
  res.writeHead(status, {
    "content-type": "application/json; charset=utf-8",
    "cache-control": "no-store",
    "x-content-type-options": "nosniff",
    "referrer-policy": "no-referrer",
  });
  res.end(payload);
}

function errorBody(error: ExplorerError, durationMs?: number): ErrorPayload {
  return {
    ok: false,
    durationMs,
    error: {
      kind: error.kind,
      message: error.message,
      details: error.details,
    },
  };
}

function readBearer(req: IncomingMessage): string | undefined {
  const header = req.headers.authorization;
  if (typeof header !== "string") return undefined;
  const match = /^Bearer\s+(\S+)\s*$/i.exec(header);
  const token = match?.[1];
  if (!token || token === "undefined") return undefined;
  return token;
}

async function readJson(req: IncomingMessage): Promise<unknown> {
  const chunks: Buffer[] = [];
  let size = 0;
  for await (const chunk of req) {
    const buffer = Buffer.isBuffer(chunk) ? chunk : Buffer.from(chunk);
    size += buffer.length;
    if (size > MAX_JSON_BODY_BYTES) {
      throw new ExplorerError("validation", "The request body is too large.", 413);
    }
    chunks.push(buffer);
  }
  if (chunks.length === 0) return {};
  try {
    return JSON.parse(Buffer.concat(chunks).toString("utf8")) as unknown;
  } catch {
    throw new ExplorerError("validation", "The request body must be JSON.", 400);
  }
}

function lock<T>(session: SessionRecord, fn: () => Promise<T>): Promise<T> {
  const previous = session.tail;
  let release = () => undefined as void;
  const gate = new Promise<void>((resolve) => {
    release = resolve;
  });
  session.tail = previous.then(() => gate);
  return previous.then(fn).finally(() => release());
}

async function serveStatic(res: ServerResponse, staticDir: string, urlPath: string): Promise<boolean> {
  const requested = urlPath === "/" ? "/index.html" : urlPath;
  const filePath = path.normalize(path.join(staticDir, requested));
  if (!filePath.startsWith(path.normalize(staticDir))) return false;
  try {
    const info = await stat(filePath);
    if (!info.isFile()) return false;
    const ext = path.extname(filePath);
    res.writeHead(200, { "content-type": MIME[ext] ?? "application/octet-stream" });
    createReadStream(filePath).pipe(res);
    return true;
  } catch {
    return false;
  }
}

export function createApp(options: AppOptions): {
  handler: (req: IncomingMessage, res: ServerResponse) => void;
  close: () => Promise<void>;
} {
  const timeoutMs = options.timeoutMs ?? DEFAULT_TIMEOUT_MS;
  const sessionTtlMs = options.sessionTtlMs ?? DEFAULT_SESSION_TTL_MS;
  const connect = options.connect ?? connectSuperdocs;
  const staticDir = options.staticDir ?? path.join(projectRoot(), "dist", "client");
  const sessions = new Map<string, SessionRecord>();

  const timer = setInterval(() => {
    const now = Date.now();
    for (const [id, session] of sessions) {
      if (now - session.lastUsed > sessionTtlMs) {
        sessions.delete(id);
        void session.connection.close();
      }
    }
  }, 30_000);
  timer.unref?.();

  function publicConfig(): PublicConfig {
    return {
      mcpEndpoint: options.endpoint,
      transport: "streamable-http",
      auth: options.serverApiKey ? "server" : "client",
    };
  }

  function requireSession(id: string): SessionRecord {
    const session = sessions.get(id);
    if (!session) throw new ExplorerError("session", "This explorer session was not found. Connect again.", 404);
    session.lastUsed = Date.now();
    return session;
  }

  async function listSessionTools(session: SessionRecord): Promise<ToolDescriptor[]> {
    const tools = await session.connection.listTools();
    session.tools = tools;
    return tools;
  }

  async function handle(req: IncomingMessage, res: ServerResponse): Promise<void> {
    const url = new URL(req.url ?? "/", "http://127.0.0.1");
    const pathname = url.pathname.replace(/\/+$/, "") || "/";
    if (!pathname.startsWith("/api")) {
      const served = await serveStatic(res, staticDir, url.pathname);
      if (served) return;
      const fallback = await serveStatic(res, staticDir, "/index.html");
      if (fallback) return;
      sendJson(res, 404, { ok: false, error: { kind: "session", message: "Not found." } });
      return;
    }

    try {
      if (req.method === "GET" && pathname === "/api/config") {
        sendJson(res, 200, publicConfig());
        return;
      }

      if (req.method === "POST" && pathname === "/api/sessions") {
        const provided = readBearer(req);
        const apiKey = provided || options.serverApiKey;
        if (!apiKey) {
          throw new ExplorerError(
            "authentication",
            "Add a SuperDocs API key. Server-side SUPERDOCS_API_KEY is not set.",
            401,
          );
        }
        const connection = await connect({
          endpoint: options.endpoint,
          apiKey,
          timeoutMs,
        });
        const id = randomUUID();
        sessions.set(id, {
          id,
          connection,
          tools: null,
          secret: apiKey,
          lastUsed: Date.now(),
          tail: Promise.resolve(),
        });
        sendJson(
          res,
          201,
          {
            sessionId: id,
            server: connection.server,
          },
          apiKey,
        );
        return;
      }

      const toolMatch = /^\/api\/sessions\/([^/]+)\/tools$/.exec(pathname);
      const callMatch = /^\/api\/sessions\/([^/]+)\/call$/.exec(pathname);
      const sessionMatch = /^\/api\/sessions\/([^/]+)$/.exec(pathname);

      if (req.method === "DELETE" && sessionMatch) {
        const session = sessions.get(sessionMatch[1]);
        if (session) {
          sessions.delete(session.id);
          await session.connection.close();
        }
        res.writeHead(204, { "cache-control": "no-store" });
        res.end();
        return;
      }

      if (req.method === "GET" && toolMatch) {
        const session = requireSession(toolMatch[1]);
        const tools = await lock(session, () => listSessionTools(session));
        sendJson(res, 200, { tools, server: session.connection.server }, session.secret);
        return;
      }

      if (req.method === "POST" && callMatch) {
        const session = requireSession(callMatch[1]);
        const body = await readJson(req);
        const record = body && typeof body === "object" ? (body as Record<string, unknown>) : {};
        const name = typeof record.name === "string" ? record.name : "";
        if (!name) throw new ExplorerError("validation", "Choose a tool before executing.", 400);
        const args = record.arguments === undefined ? {} : record.arguments;
        const started = Date.now();
        const outcome = await lock(session, async () => {
          let tools = session.tools;
          if (!tools || !tools.some((tool) => tool.name === name)) {
            tools = await listSessionTools(session);
          }
          const tool = tools.find((entry) => entry.name === name);
          if (!tool) {
            throw new ExplorerError(
              "validation",
              "That tool is not in the list returned by the MCP server. Refresh the tools and try again.",
              400,
            );
          }
          const validated = validateToolArguments(tool.inputSchema as JsonSchema, args);
          if (!validated.ok) {
            throw new ExplorerError("validation", "The arguments do not match this tool's schema.", 400, validated.errors);
          }
          const result = await session.connection.callTool(name, validated.data);
          const toolError = result.isError === true;
          const payload: ToolCallPayload = {
            ok: true,
            durationMs: Date.now() - started,
            request: { name, arguments: validated.data },
            result,
            toolError,
          };
          return payload;
        });
        sendJson(res, 200, outcome, session.secret);
        return;
      }

      sendJson(res, 404, { ok: false, error: { kind: "session", message: "Not found." } });
    } catch (error) {
      const explorer = error instanceof ExplorerError ? error : new ExplorerError("connection", "The request failed.", 500);
      sendJson(res, explorer.status, errorBody(explorer));
    }
  }

  return {
    handler(req, res) {
      void handle(req, res).catch((error: unknown) => {
        const explorer = error instanceof ExplorerError ? error : new ExplorerError("connection", "The request failed.", 500);
        if (!res.headersSent) sendJson(res, explorer.status, errorBody(explorer));
        else res.end();
      });
    },
    async close() {
      clearInterval(timer);
      const closing = [...sessions.values()];
      sessions.clear();
      await Promise.all(closing.map((session) => session.connection.close()));
    },
  };
}

export async function startApp(options: AppOptions): Promise<RunningApp> {
  const app = createApp(options);
  const server: Server = createServer(app.handler);
  const host = options.host ?? "127.0.0.1";
  const port = options.port ?? 0;
  await new Promise<void>((resolve, reject) => {
    server.once("error", reject);
    server.listen(port, host, () => resolve());
  });
  const address = server.address();
  const bound = typeof address === "object" && address ? address.port : port;
  return {
    baseUrl: `http://${host}:${bound}`,
    async close() {
      await app.close();
      await new Promise<void>((resolve, reject) => server.close((error) => (error ? reject(error) : resolve())));
    },
  };
}

