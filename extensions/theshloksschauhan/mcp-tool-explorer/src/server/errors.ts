import { UnauthorizedError } from "@modelcontextprotocol/sdk/client/auth.js";
import { StreamableHTTPError } from "@modelcontextprotocol/sdk/client/streamableHttp.js";
import { McpError } from "@modelcontextprotocol/sdk/types.js";
import { redactSecrets } from "../shared/redact.js";
import type { ErrorKind, FieldError } from "../shared/types.js";

export class ExplorerError extends Error {
  readonly kind: ErrorKind;
  readonly status: number;
  readonly details?: FieldError[];

  constructor(kind: ErrorKind, message: string, status: number, details?: FieldError[]) {
    super(message);
    this.name = "ExplorerError";
    this.kind = kind;
    this.status = status;
    this.details = details;
  }
}

function textOf(error: unknown): string {
  if (error instanceof Error) return error.message;
  return String(error);
}

export function classifyTransportError(error: unknown, secret?: string): ExplorerError {
  if (error instanceof ExplorerError) return error;
  const message = redactSecrets(textOf(error), secret ? [secret] : []);
  const httpStatus = error instanceof StreamableHTTPError ? error.code : undefined;

  if (
    error instanceof UnauthorizedError ||
    httpStatus === 401 ||
    httpStatus === 403 ||
    /unauthorized|authentication required|invalid access token|invalid_token/i.test(message)
  ) {
    return new ExplorerError(
      "authentication",
      "Authentication failed. Check the SuperDocs API key.",
      401,
    );
  }
  if (httpStatus === 429 || /rate limit|too many requests/i.test(message)) {
    return new ExplorerError("protocol", "SuperDocs rate-limited the request. Wait and try again.", 429);
  }
  if (/timed out|timeout|aborted/i.test(message)) {
    return new ExplorerError("timeout", "The MCP request timed out before the server responded.", 504);
  }
  if (/ECONNREFUSED|ENOTFOUND|EAI_AGAIN|fetch failed|network|socket/i.test(message)) {
    return new ExplorerError("connection", "Could not reach the SuperDocs MCP server.", 502);
  }
  if (httpStatus === 404 || /session.*(expired|not found|interrupted|terminated)|invalid session/i.test(message)) {
    return new ExplorerError("session", "The MCP session ended. Connect again.", 409);
  }
  if (error instanceof McpError) {
    return new ExplorerError("protocol", message || "The MCP server rejected the request.", 502);
  }
  if (typeof httpStatus === "number" && httpStatus >= 400) {
    return new ExplorerError("protocol", message || `The MCP server returned HTTP ${httpStatus}.`, 502);
  }
  return new ExplorerError("connection", message || "Could not complete the MCP request.", 502);
}
