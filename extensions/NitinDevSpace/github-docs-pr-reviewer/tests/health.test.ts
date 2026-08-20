import { describe, expect, it } from "vitest";
import { buildApp } from "../src/app.js";
import { loadConfig } from "../src/config.js";

describe("health endpoint", () => {
  it("returns service health", async () => {
    const app = buildApp({
      config: loadConfig({ NODE_ENV: "test" })
    });

    const response = await app.inject({
      method: "GET",
      url: "/health"
    });

    expect(response.statusCode).toBe(200);
    expect(response.json()).toEqual({
      ok: true,
      service: "docs-pr-reviewer",
      env: "test"
    });
  });
});

