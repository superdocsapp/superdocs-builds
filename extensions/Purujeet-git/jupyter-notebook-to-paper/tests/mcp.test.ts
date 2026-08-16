import { describe, expect, it } from "vitest";
import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { InMemoryTransport } from "@modelcontextprotocol/sdk/inMemory.js";
import { createPaperMcpServer } from "../src/mcpServer.js";

describe("MCP integration", () => {
  it("exposes and invokes the paper preview tool through MCP", async () => {
    const server = createPaperMcpServer();
    const client = new Client({ name: "test-client", version: "1.0.0" }, { capabilities: {} });
    const [clientTransport, serverTransport] = InMemoryTransport.createLinkedPair();
    await Promise.all([server.connect(serverTransport), client.connect(clientTransport)]);

    const tools = await client.listTools();
    const result = await client.callTool({
      name: "paper_preview",
      arguments: { notebookPath: "examples/synthetic_research.ipynb" },
    });
    const text = result.content?.find((item) => item.type === "text")?.text ?? "";

    await client.close();
    await server.close();
    expect(tools.tools.map((tool) => tool.name)).toContain("paper_preview");
    expect(text).toContain("Synthetic Research Study");
  });
});
