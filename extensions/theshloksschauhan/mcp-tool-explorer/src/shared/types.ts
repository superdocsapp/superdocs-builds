export type JsonSchema = {
  type?: string | string[];
  properties?: Record<string, JsonSchema>;
  required?: string[];
  items?: JsonSchema | JsonSchema[];
  enum?: unknown[];
  const?: unknown;
  description?: string;
  title?: string;
  default?: unknown;
  anyOf?: JsonSchema[];
  oneOf?: JsonSchema[];
  nullable?: boolean;
  additionalProperties?: boolean | JsonSchema;
  format?: string;
  minimum?: number;
  maximum?: number;
  minLength?: number;
  maxLength?: number;
  minItems?: number;
  maxItems?: number;
  [key: string]: unknown;
};

export type ToolDescriptor = {
  name: string;
  title?: string;
  description?: string;
  inputSchema: JsonSchema;
};

export type FieldError = {
  path: string;
  message: string;
};

export type ToolContent = Record<string, unknown>;

export type ToolCallPayload = {
  ok: true;
  durationMs: number;
  request: {
    name: string;
    arguments: Record<string, unknown>;
  };
  result: ToolContent;
  toolError: boolean;
};

export type ErrorKind =
  | "validation"
  | "authentication"
  | "connection"
  | "timeout"
  | "protocol"
  | "session";

export type ErrorPayload = {
  ok: false;
  durationMs?: number;
  error: {
    kind: ErrorKind;
    message: string;
    details?: FieldError[];
  };
};

export type PublicConfig = {
  mcpEndpoint: string;
  transport: "streamable-http";
  auth: "server" | "client";
};
