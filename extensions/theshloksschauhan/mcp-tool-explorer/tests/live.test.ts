import { describe, expect, it } from "vitest";
import { createDraft, submissionFromDraft } from "../src/shared/schema.js";
import type { JsonSchema, ToolDescriptor } from "../src/shared/types.js";
import { DEFAULT_MCP_ENDPOINT } from "../src/server/config.js";
import { startApp } from "../src/server/http.js";

const apiKey = process.env.SUPERDOCS_API_KEY?.trim();

describe.skipIf(!apiKey)("live SuperDocs MCP", () => {
  it("discovers tools and executes one with an empty required set", async () => {
    const key = apiKey as string;
    const app = await startApp({
      endpoint: process.env.SUPERDOCS_MCP_URL?.trim() || DEFAULT_MCP_ENDPOINT,
      serverApiKey: key,
      timeoutMs: 45_000,
      sessionTtlMs: 60_000,
    });
    try {
      const configResponse = await fetch(`${app.baseUrl}/api/config`);
      const config = await configResponse.json();
      expect(JSON.stringify(config).includes(key)).toBe(false);

      const opened = await fetch(`${app.baseUrl}/api/sessions`, { method: "POST" });
      expect(opened.status).toBe(201);
      const session = (await opened.json()) as { sessionId: string };
      expect(JSON.stringify(session).includes(key)).toBe(false);

      const listed = await fetch(`${app.baseUrl}/api/sessions/${session.sessionId}/tools`);
      expect(listed.status).toBe(200);
      const toolsBody = (await listed.json()) as { tools: ToolDescriptor[] };
      expect(toolsBody.tools.length).toBeGreaterThan(0);
      expect(JSON.stringify(toolsBody).includes(key)).toBe(false);
      const names = new Set(toolsBody.tools.map((tool) => tool.name));
      expect(names.size).toBe(toolsBody.tools.length);

      const requiredTool = toolsBody.tools.find(
        (tool) => Array.isArray(tool.inputSchema.required) && tool.inputSchema.required.length > 0,
      );
      if (requiredTool) {
        const rejected = await fetch(`${app.baseUrl}/api/sessions/${session.sessionId}/call`, {
          method: "POST",
          headers: { "content-type": "application/json" },
          body: JSON.stringify({ name: requiredTool.name, arguments: {} }),
        });
        expect(rejected.status).toBe(400);
        const rejectedBody = (await rejected.json()) as { error: { kind: string } };
        expect(rejectedBody.error.kind).toBe("validation");
      }

      const health = toolsBody.tools.find((tool) => tool.name === "health");
      expect(health).toBeTruthy();
      const submission = submissionFromDraft(health!.inputSchema as JsonSchema, createDraft(health!.inputSchema));
      expect(submission.ok).toBe(true);
      if (!submission.ok) return;
      const called = await fetch(`${app.baseUrl}/api/sessions/${session.sessionId}/call`, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ name: health!.name, arguments: submission.value }),
      });
      const calledBody = await called.json();
      expect(called.status).toBe(200);
      expect(JSON.stringify(calledBody).includes(key)).toBe(false);
      expect(calledBody.ok).toBe(true);
      expect(typeof calledBody.durationMs).toBe("number");
    } finally {
      await app.close();
    }
  }, 60_000);
});
