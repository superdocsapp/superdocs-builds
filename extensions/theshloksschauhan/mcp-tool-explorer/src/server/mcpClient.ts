import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { StreamableHTTPClientTransport } from "@modelcontextprotocol/sdk/client/streamableHttp.js";
import type { JsonSchema, ToolDescriptor } from "../shared/types.js";
import { classifyTransportError } from "./errors.js";

export type McpConnection = {
  listTools: () => Promise<ToolDescriptor[]>;
  callTool: (name: string, args: Record<string, unknown>) => Promise<Record<string, unknown>>;
  close: () => Promise<void>;
  server: {
    name?: string;
    version?: string;
    protocolVersion?: string;
    instructions?: string;
  };
};

const MAX_TOOL_PAGES = 20;

function asSchema(value: unknown): JsonSchema {
  if (value && typeof value === "object" && !Array.isArray(value)) return value as JsonSchema;
  return { type: "object", properties: {} };
}

export async function connectSuperdocs(options: {
  endpoint: string;
  apiKey: string;
  timeoutMs: number;
  fetchImpl?: typeof fetch;
}): Promise<McpConnection> {
  const transport = new StreamableHTTPClientTransport(new URL(options.endpoint), {
    requestInit: {
      headers: {
        Authorization: `Bearer ${options.apiKey}`,
      },
    },
    fetch: options.fetchImpl,
  });
  const client = new Client(
    { name: "superdocs-mcp-tool-explorer", version: "1.0.0" },
    { capabilities: {} },
  );

  try {
    await client.connect(transport, { timeout: options.timeoutMs });
  } catch (error) {
    await transport.close().catch(() => undefined);
    throw classifyTransportError(error, options.apiKey);
  }

  const version = client.getServerVersion();
  const server = {
    name: version?.name,
    version: version?.version,
    protocolVersion: transport.protocolVersion,
    instructions: client.getInstructions(),
  };

  return {
    server,
    async listTools() {
      const tools: ToolDescriptor[] = [];
      const seenCursors = new Set<string>();
      let cursor: string | undefined;
      for (let page = 0; page < MAX_TOOL_PAGES; page += 1) {
        let listed;
        try {
          listed = await client.listTools(cursor ? { cursor } : undefined, { timeout: options.timeoutMs });
        } catch (error) {
          throw classifyTransportError(error, options.apiKey);
        }
        for (const tool of listed.tools) {
          tools.push({
            name: tool.name,
            title: tool.title,
            description: tool.description,
            inputSchema: asSchema(tool.inputSchema),
          });
        }
        if (!listed.nextCursor || seenCursors.has(listed.nextCursor)) break;
        seenCursors.add(listed.nextCursor);
        cursor = listed.nextCursor;
      }
      return tools;
    },
    async callTool(name, args) {
      try {
        const result = await client.callTool({ name, arguments: args }, undefined, { timeout: options.timeoutMs });
        return result as Record<string, unknown>;
      } catch (error) {
        throw classifyTransportError(error, options.apiKey);
      }
    },
    async close() {
      await transport.terminateSession().catch(() => undefined);
      await client.close().catch(() => undefined);
    },
  };
}
