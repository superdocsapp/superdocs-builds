import { createServer } from "node:http";

const PORT = Number(process.env.PORT || 8787);
const API_KEY = process.env.SUPERDOCS_API_KEY;
const ALLOWED_ORIGIN = process.env.ALLOWED_EXTENSION_ORIGIN;
const API_BASE = "https://api.superdocs.app";

function log(event, details = {}) {
  console.info(`[Chat to SuperDocs bridge] ${event}`, details);
}

if (!API_KEY || !ALLOWED_ORIGIN) {
  throw new Error("Set SUPERDOCS_API_KEY and ALLOWED_EXTENSION_ORIGIN before starting the bridge.");
}

function allowOrigin(request, response) {
  const receivedOrigin = request.headers.origin ?? "(no Origin header)";
  const extensionOrigin = request.headers["x-chat-to-superdocs-origin"];
  if (receivedOrigin !== ALLOWED_ORIGIN && extensionOrigin !== ALLOWED_ORIGIN) {
    console.warn(`Rejected bridge request: expected ${ALLOWED_ORIGIN}; received Origin ${receivedOrigin}; extension header ${extensionOrigin ?? "(missing)"}.`);
    response.setHeader("Access-Control-Allow-Origin", ALLOWED_ORIGIN);
    return false;
  }
  response.setHeader("Access-Control-Allow-Origin", ALLOWED_ORIGIN);
  response.setHeader("Access-Control-Allow-Methods", "GET, POST, OPTIONS");
  response.setHeader("Access-Control-Allow-Headers", "content-type, x-chat-to-superdocs-origin");
  return true;
}

async function jsonBody(request) {
  const chunks = [];
  for await (const chunk of request) chunks.push(chunk);
  try { return JSON.parse(Buffer.concat(chunks).toString("utf8")); } catch { throw new Error("Request body must be JSON."); }
}

async function upstream(path, init = {}) {
  const response = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: { authorization: `Bearer ${API_KEY}`, "content-type": "application/json", ...(init.headers ?? {}) },
  });
  if (!response.ok) {
    const message = await response.text() || `SuperDocs returned ${response.status}.`;
    log("upstream failure", { path, status: response.status });
    throw new Error(message);
  }
  log("upstream success", { path, status: response.status });
  return response;
}

function sendJson(response, status, body) {
  response.writeHead(status, { "content-type": "application/json" });
  response.end(JSON.stringify(body));
}

const server = createServer(async (request, response) => {
  try {
    if (request.method === "OPTIONS") {
      response.setHeader("Access-Control-Allow-Origin", ALLOWED_ORIGIN);
      response.setHeader("Access-Control-Allow-Methods", "GET, POST, OPTIONS");
      response.setHeader("Access-Control-Allow-Headers", "content-type, x-chat-to-superdocs-origin");
      return response.writeHead(204).end();
    }
    if (!allowOrigin(request, response)) {
      return sendJson(response, 403, { error: "Untrusted extension origin.", expected_origin: ALLOWED_ORIGIN, received_origin: request.headers.origin ?? null, received_extension_origin: request.headers["x-chat-to-superdocs-origin"] ?? null });
    }
    const path = new URL(request.url, "http://localhost").pathname;
    log("bridge request", { method: request.method, path });
    if (request.method === "GET" && path === "/api/templates") {
      const upstreamResponse = await upstream("/v1/templates");
      return sendJson(response, 200, await upstreamResponse.json());
    }
    if (request.method === "GET" && path === "/api/documents") {
      const upstreamResponse = await upstream("/v1/documents");
      return sendJson(response, 200, await upstreamResponse.json());
    }
    if (request.method === "POST" && path === "/api/jobs") {
      const body = await jsonBody(request);
      const upstreamResponse = await upstream("/v1/chat/async", { method: "POST", body: JSON.stringify(body) });
      return sendJson(response, 202, await upstreamResponse.json());
    }
    const jobMatch = path.match(/^\/api\/jobs\/([^/]+)$/);
    if (request.method === "GET" && jobMatch) {
      const upstreamResponse = await upstream(`/v1/jobs/${encodeURIComponent(jobMatch[1])}`);
      return sendJson(response, 200, await upstreamResponse.json());
    }
    const approveMatch = path.match(/^\/api\/sessions\/([^/]+)\/approve$/);
    if (request.method === "POST" && approveMatch) {
      const body = await jsonBody(request);
      const upstreamResponse = await upstream(`/v1/chat/${encodeURIComponent(approveMatch[1])}/approve`, { method: "POST", body: JSON.stringify(body) });
      return sendJson(response, 200, await upstreamResponse.json());
    }
    const blankMatch = path.match(/^\/api\/sessions\/([^/]+)\/documents\/blank$/);
    if (request.method === "POST" && blankMatch) {
      const upstreamResponse = await upstream(`/v1/sessions/${encodeURIComponent(blankMatch[1])}/documents/blank`, { method: "POST", body: "{}" });
      return sendJson(response, 200, await upstreamResponse.json());
    }
    const sessionDocumentsMatch = path.match(/^\/api\/sessions\/([^/]+)\/documents$/);
    if (request.method === "GET" && sessionDocumentsMatch) {
      const upstreamResponse = await upstream(`/v1/sessions/${encodeURIComponent(sessionDocumentsMatch[1])}/documents`);
      return sendJson(response, 200, await upstreamResponse.json());
    }
    const saveMatch = path.match(/^\/api\/sessions\/([^/]+)\/documents\/([^/]+)\/save$/);
    if (request.method === "POST" && saveMatch) {
      const body = await jsonBody(request);
      const upstreamResponse = await upstream(`/v1/sessions/${encodeURIComponent(saveMatch[1])}/documents/${encodeURIComponent(saveMatch[2])}/save`, { method: "POST", body: JSON.stringify(body) });
      return sendJson(response, 200, await upstreamResponse.json());
    }
    if (request.method === "POST" && path === "/api/export") {
      const body = await jsonBody(request);
      const upstreamResponse = await upstream("/v1/documents/export", { method: "POST", body: JSON.stringify(body) });
      response.writeHead(200, { "content-type": upstreamResponse.headers.get("content-type") || "application/octet-stream", "content-disposition": upstreamResponse.headers.get("content-disposition") || "attachment" });
      return response.end(Buffer.from(await upstreamResponse.arrayBuffer()));
    }
    return sendJson(response, 404, { error: "Route not found." });
  } catch (error) {
    log("bridge failure", { message: error instanceof Error ? error.message : "Bridge error." });
    return sendJson(response, 502, { error: error instanceof Error ? error.message : "Bridge error." });
  }
});

server.listen(PORT, "127.0.0.1", () => console.log(`Chat to SuperDocs bridge listening on http://127.0.0.1:${PORT}`));
