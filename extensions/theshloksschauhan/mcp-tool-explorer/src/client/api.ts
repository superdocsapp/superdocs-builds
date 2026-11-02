import type { ErrorPayload, PublicConfig, ToolCallPayload, ToolDescriptor } from "../shared/types.js";

export class ApiError extends Error {
  readonly status: number;
  readonly payload: ErrorPayload;

  constructor(status: number, payload: ErrorPayload) {
    super(payload.error.message);
    this.status = status;
    this.payload = payload;
  }
}

async function parse<T>(response: Response): Promise<T> {
  const text = await response.text();
  const body = text ? (JSON.parse(text) as T & Partial<ErrorPayload>) : {};
  if (!response.ok) {
    const payload: ErrorPayload =
      body && typeof body === "object" && "error" in body && body.error
        ? (body as ErrorPayload)
        : { ok: false, error: { kind: "connection", message: response.statusText || "Request failed." } };
    throw new ApiError(response.status, payload);
  }
  return body as T;
}

export function fetchConfig(): Promise<PublicConfig> {
  return fetch("/api/config").then((response) => parse<PublicConfig>(response));
}

export function openSession(apiKey?: string): Promise<{
  sessionId: string;
  server: { name?: string; version?: string; protocolVersion?: string; instructions?: string };
}> {
  return fetch("/api/sessions", {
    method: "POST",
    headers: apiKey ? { Authorization: `Bearer ${apiKey}` } : {},
  }).then((response) =>
    parse<{
      sessionId: string;
      server: { name?: string; version?: string; protocolVersion?: string; instructions?: string };
    }>(response),
  );
}

export function closeSession(sessionId: string): Promise<void> {
  return fetch(`/api/sessions/${sessionId}`, { method: "DELETE" }).then(() => undefined);
}

export function fetchTools(sessionId: string): Promise<{ tools: ToolDescriptor[] }> {
  return fetch(`/api/sessions/${sessionId}/tools`).then((response) => parse<{ tools: ToolDescriptor[] }>(response));
}

export function callTool(
  sessionId: string,
  name: string,
  args: Record<string, unknown>,
): Promise<ToolCallPayload> {
  return fetch(`/api/sessions/${sessionId}/call`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ name, arguments: args }),
  }).then((response) => parse<ToolCallPayload>(response));
}
