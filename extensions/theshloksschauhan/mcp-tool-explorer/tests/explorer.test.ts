import { afterEach, describe, expect, it } from "vitest";
import { startApp, type RunningApp } from "../src/server/http.js";
import { startFixture, type Fixture } from "./mcpFixture.js";

const secret = "sk_abcdef0123456789abcdef0123456789";

const nestedSchema = {
  type: "object",
  required: ["address"],
  properties: {
    address: {
      type: "object",
      required: ["city"],
      properties: {
        city: { type: "string" },
        tags: { type: "array", items: { type: "string" } },
      },
    },
  },
};

async function boot(
  tools: Parameters<typeof startFixture>[0]["tools"],
  extra: Partial<Parameters<typeof startFixture>[0]> = {},
  timeoutMs = 5_000,
) {
  const fixture = await startFixture({ apiKey: secret, tools, ...extra });
  const app = await startApp({
    endpoint: fixture.url,
    serverApiKey: extra.failAuth ? undefined : secret,
    timeoutMs,
    sessionTtlMs: 60_000,
  });
  running.push(app, fixture);
  return { fixture, app };
}

const running: Array<RunningApp | Fixture> = [];

afterEach(async () => {
  while (running.length) {
    const item = running.pop();
    if (item) await item.close();
  }
});

async function connect(app: RunningApp): Promise<string> {
  const response = await fetch(`${app.baseUrl}/api/sessions`, { method: "POST" });
  expect(response.status).toBe(201);
  const body = (await response.json()) as { sessionId: string; server: { name?: string } };
  expect(JSON.stringify(body).includes(secret)).toBe(false);
  expect(body.server.name).toBe("fixture-superdocs");
  return body.sessionId;
}

describe("MCP discovery and invocation", () => {
  it("discovers tools from the server, including a later page, and does not add its own", async () => {
    const { fixture, app } = await boot(
      [
        { name: "alpha_tool", description: "first", inputSchema: { type: "object", properties: {} } },
        { name: "beta_tool", description: "second", inputSchema: { type: "object", properties: {} } },
        { name: "gamma_tool", description: "third", inputSchema: { type: "object", properties: {} } },
      ],
      { pageSize: 2 },
    );
    const sessionId = await connect(app);
    const listed = await fetch(`${app.baseUrl}/api/sessions/${sessionId}/tools`);
    const body = (await listed.json()) as { tools: Array<{ name: string }> };
    expect(body.tools.map((tool) => tool.name)).toEqual(["alpha_tool", "beta_tool", "gamma_tool"]);
    expect(fixture.sessionHeaders.length).toBeGreaterThan(0);
  });

  it("returns a different server list without a client-side catalog", async () => {
    const { app } = await boot([
      { name: "only_new_tool", description: "added later", inputSchema: { type: "object", properties: {} } },
    ]);
    const sessionId = await connect(app);
    const listed = await fetch(`${app.baseUrl}/api/sessions/${sessionId}/tools`);
    const body = (await listed.json()) as { tools: Array<{ name: string }> };
    expect(body.tools.map((tool) => tool.name)).toEqual(["only_new_tool"]);
  });

  it("validates required nested fields before calling the tool", async () => {
    const { fixture, app } = await boot([
      { name: "nested_tool", description: "nested", inputSchema: nestedSchema },
    ]);
    const sessionId = await connect(app);
    await fetch(`${app.baseUrl}/api/sessions/${sessionId}/tools`);
    const response = await fetch(`${app.baseUrl}/api/sessions/${sessionId}/call`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ name: "nested_tool", arguments: { address: { tags: ["a"] } } }),
    });
    expect(response.status).toBe(400);
    const body = (await response.json()) as { error: { kind: string; details: Array<{ message: string }> } };
    expect(body.error.kind).toBe("validation");
    expect(body.error.details.some((detail) => detail.message === "city is required")).toBe(true);
    expect(fixture.calls).toHaveLength(0);
  });

  it("calls the discovered tool and returns the server response", async () => {
    const { app } = await boot([
      { name: "nested_tool", description: "nested", inputSchema: nestedSchema },
    ]);
    const sessionId = await connect(app);
    await fetch(`${app.baseUrl}/api/sessions/${sessionId}/tools`);
    const response = await fetch(`${app.baseUrl}/api/sessions/${sessionId}/call`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ name: "nested_tool", arguments: { address: { city: "Pune", tags: ["a"] } } }),
    });
    expect(response.status).toBe(200);
    const body = (await response.json()) as {
      toolError: boolean;
      request: { arguments: { address: { city: string } } };
      result: { structuredContent: { arguments: { address: { city: string } } } };
    };
    expect(body.toolError).toBe(false);
    expect(body.request.arguments.address.city).toBe("Pune");
    expect(body.result.structuredContent.arguments.address.city).toBe("Pune");
    expect(JSON.stringify(body).includes(secret)).toBe(false);
  });

  it("surfaces tool errors, protocol errors, auth failures, and timeouts", async () => {
    const tool = { name: "plain_tool", description: "plain", inputSchema: { type: "object", properties: {} } };

    const toolError = await boot([tool], { toolError: true });
    let sessionId = await connect(toolError.app);
    await fetch(`${toolError.app.baseUrl}/api/sessions/${sessionId}/tools`);
    let response = await fetch(`${toolError.app.baseUrl}/api/sessions/${sessionId}/call`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ name: "plain_tool", arguments: {} }),
    });
    let body = (await response.json()) as { toolError?: boolean; error?: { kind: string; message?: string } };
    expect(body.toolError).toBe(true);

    const protocol = await boot([tool], { protocolError: "Invalid params: missing city" });
    sessionId = await connect(protocol.app);
    await fetch(`${protocol.app.baseUrl}/api/sessions/${sessionId}/tools`);
    response = await fetch(`${protocol.app.baseUrl}/api/sessions/${sessionId}/call`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ name: "plain_tool", arguments: {} }),
    });
    body = (await response.json()) as { error?: { kind: string; message: string } };
    expect(response.status).toBe(502);
    expect(body.error?.kind).toBe("protocol");
    expect(body.error?.message).toContain("missing city");

    const unauth = await boot([tool], { failAuth: true });
    response = await fetch(`${unauth.app.baseUrl}/api/sessions`, {
      method: "POST",
      headers: { Authorization: `Bearer ${secret}` },
    });
    expect(response.status).toBe(401);
    body = (await response.json()) as { error?: { kind: string } };
    expect(body.error?.kind).toBe("authentication");
    expect(JSON.stringify(body).includes(secret)).toBe(false);

    const missingKey = await startApp({ endpoint: toolError.fixture.url, timeoutMs: 5_000, sessionTtlMs: 60_000 });
    running.push(missingKey);
    response = await fetch(`${missingKey.baseUrl}/api/sessions`, { method: "POST" });
    expect(response.status).toBe(401);

    const slow = await boot([tool], { callDelayMs: 800 }, 200);
    sessionId = await connect(slow.app);
    await fetch(`${slow.app.baseUrl}/api/sessions/${sessionId}/tools`);
    response = await fetch(`${slow.app.baseUrl}/api/sessions/${sessionId}/call`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ name: "plain_tool", arguments: {} }),
    });
    body = (await response.json()) as { error?: { kind: string } };
    expect(body.error?.kind).toBe("timeout");
  });

  it("reports an interrupted session", async () => {
    const { app } = await boot(
      [{ name: "plain_tool", description: "plain", inputSchema: { type: "object", properties: {} } }],
      { dropSession: true },
    );
    const sessionId = await connect(app);
    const listed = await fetch(`${app.baseUrl}/api/sessions/${sessionId}/tools`);
    expect(listed.status).toBe(409);
    const body = (await listed.json()) as { error: { kind: string } };
    expect(body.error.kind).toBe("session");
  });

  it("does not put the server key in public config", async () => {
    const { app } = await boot([]);
    const response = await fetch(`${app.baseUrl}/api/config`);
    const body = (await response.json()) as { auth: string; transport: string; mcpEndpoint: string };
    expect(body.auth).toBe("server");
    expect(body.transport).toBe("streamable-http");
    expect(JSON.stringify(body).includes(secret)).toBe(false);
    expect(JSON.stringify(body).includes("sk_")).toBe(false);
  });
});
